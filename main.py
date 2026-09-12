import hashlib
import logging
import os
import subprocess
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler

from flask import Flask, jsonify, request
from flask_cors import CORS

try:  # pywin32 ya está en requirements.txt; en un portátil de desarrollo no.
    import win32file
    import pywintypes
except ImportError:  # pragma: no cover - sólo fuera de Windows
    win32file = None
    pywintypes = None


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, 'logs')

# El instalador configura AppStdout/AppStderr a logs\*.log pero NUNCA crea la
# carpeta, así que hasta ahora los `print()` de este demonio no quedaban en
# ningún sitio: cuando una cajera reportaba «el cierre salió incompleto» no
# había NADA que mirar del lado del demonio. Un log propio, rotado, con el
# nombre/tamaño/sha1 de cada archivo servido, convierte esa anécdota en algo
# verificable.
os.makedirs(LOG_DIR, exist_ok=True)
_handler = RotatingFileHandler(
    os.path.join(LOG_DIR, 'api.log'), maxBytes=2_000_000, backupCount=5, encoding='utf-8')
_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
logging.getLogger().addHandler(_handler)
logging.getLogger().setLevel(logging.INFO)
log = logging.getLogger('vpos')


app = Flask(__name__)
CORS(app)
app.config['CORS_HEADERS'] = 'Content-Type'


# El VPOS escribe estos archivos con la codificación de Windows en español.
# `open(path, 'r')` usaba la codificación POR DEFECTO del intérprete, que bajo
# NSSM no es necesariamente la de la consola: un byte fuera de tabla levantaba
# UnicodeDecodeError -> 500 -> el POS reintentaba hasta agotar los 60 s sin
# decir por qué. Leer en binario y decodificar con `errors='replace'` no puede
# fallar nunca, y además evita el otro caso: un archivo capturado A MEDIA
# ESCRITURA puede terminar en una secuencia multibyte partida.
ENCODING = 'cp1252'


def _leer(path):
    """Contenido, identidad y tamaño del archivo. Levanta OSError."""
    estado = os.stat(path)
    with open(path, 'rb') as fh:
        crudo = fh.read()
    texto = crudo.decode(ENCODING, errors='replace')
    return {
        'texto': texto,
        'sha1': hashlib.sha1(crudo).hexdigest(),
        'size': estado.st_size,
        'mtime': estado.st_mtime,
    }


def _comandos(texto):
    """Las líneas como comandos de impresora fiscal, o [] si no hay contenido.

    OJO con el `810Fin del documento.`: se añade SIEMPRE, así que un archivo
    truncado se imprime con un cierre de documento perfectamente formado. Por
    eso un cierre incompleto sale por la impresora sin que nada chirríe — no
    hay forma de notarlo mirando el papel. La comprobación tiene que pasar
    ANTES, aquí.
    """
    if not texto.strip():
        return []
    datos = ["800" + linea.strip('\n') for linea in texto.splitlines(keepends=True)]
    datos.append("810Fin del documento.")
    return datos


def _escritor_activo(path):
    """¿Hay otro proceso con el archivo abierto? True / False / None (no se sabe).

    Señal POSITIVA de «todavía se está escribiendo», mucho más fuerte que
    inferirlo del reloj. Se abre el archivo pidiendo modo compartido CERO
    (dwShareMode=0, denegar todo): si el VPOS lo tiene abierto, Windows lo
    rechaza. Es una apertura de SÓLO LECTURA que se cierra de inmediato — no
    escribe, no trunca, no mueve nada.

    Devuelve None fuera de Windows o si pywin32 no está: el llamador debe
    tratar «no sé» como «no concluyente», nunca como «listo».
    """
    if win32file is None:
        return None
    try:
        handle = win32file.CreateFile(
            path, win32file.GENERIC_READ, 0, None,
            win32file.OPEN_EXISTING, win32file.FILE_ATTRIBUTE_NORMAL, None)
    except Exception:
        # Sharing violation -> lo tiene alguien. Cualquier otro fallo también
        # es motivo para NO dar el archivo por terminado.
        return True
    handle.Close()
    return False


def _un_solo_txt(folder_path):
    """(ruta, None) o (None, respuesta_de_error) para la carpeta dada."""
    try:
        files_in_folder = os.listdir(folder_path)
    except OSError as error:
        log.warning('carpeta inaccesible %s: %s', folder_path, error)
        return None, {
            'exists': False,
            'data': [],
            'status': 'error',
            'motivo': 'carpeta_inaccesible',
            'message': 'No se pudo leer la carpeta %s: %s' % (folder_path, error),
        }

    txt_files = [file for file in files_in_folder if file.endswith('.txt')]

    if len(txt_files) != 1:
        log.warning('se esperaba 1 .txt en %s, hay %d: %s',
                    folder_path, len(txt_files), txt_files)
        return None, {
            'exists': False,
            'data': [],
            'status': 'error',
            'motivo': 'cero_archivos' if not txt_files else 'varios_archivos',
            'archivos': txt_files,
            'message': 'No se encontró un único archivo TXT en la carpeta. '
                       'Encontrados: %d (%s)' % (len(txt_files), ', '.join(txt_files) or 'ninguno'),
        }

    return os.path.join(folder_path, txt_files[0]), None


@app.route('/', methods=['GET'])
@app.route('/api/status', methods=['GET'])
def api():
    return jsonify({'status': 'OK'})


@app.route('/api/get_txt_file', methods=['POST'])
def get_txt_file():
    """Contenido de UN archivo dado por ruta completa.

    Este es el endpoint por el que el POS lee de verdad lo que va a imprimir,
    con la ruta que le dio el VPOS (`nombreVoucher`) — que no tiene por qué ser
    el archivo que `check_txt_file` validó. Por eso ahora se registra el sha1
    de lo servido: es la única forma de comprobar, después, que lo impreso era
    lo mismo que se dio por estable.
    """
    path = (request.json or {}).get('pathToTxt')
    if not path:
        return jsonify([])
    try:
        info = _leer(path)
    except OSError as error:
        log.error('get_txt_file no pudo leer %s: %s', path, error)
        return jsonify([])
    datos = _comandos(info['texto'])
    log.info('get_txt_file %s size=%s sha1=%s lineas=%d',
             path, info['size'], info['sha1'], max(len(datos) - 1, 0))
    return jsonify(datos)


@app.route('/api/check_txt_file', methods=['POST'])
def check_txt_file():
    """Contenido del ÚNICO .txt de la carpeta, con su identidad y tamaño.

    A raíz de «cierres que salen incompletos». El datáfono escribe el cierre de
    forma asíncrona y el manual de Megasoft (MAET-VPOSW-00) no ofrece tamaño
    esperado, marca de fin ni confirmación de escritura: un archivo recién
    creado ya «existe» desde su primer byte, así que `exists` NO significa
    «completo». Lo que se devuelve para poder decidirlo:

      motivo       por qué no hay cierre (antes era un timeout mudo de 60 s)
      file_path    QUÉ archivo se validó, para poder leer exactamente ese
      sha1         identidad del contenido: compara barato y sin ambigüedad
      size/mtime   detectar un archivo aún en escritura
      line_count   cuántas líneas lleva
      last_line    con qué termina — para aprender el terminador real de un
                   cierre completo a partir de cierres buenos, y pasar de una
                   heurística de estabilidad a una comprobación de verdad
      en_escritura True si otro proceso lo tiene abierto (Windows). None = no
                   se sabe, que NO es lo mismo que «listo».

    Todo es ADITIVO: `exists` y `data` conservan su significado, así que un POS
    viejo contra un demonio nuevo se comporta igual que antes.
    """
    folder_path = (request.json or {}).get('pathToTxt')
    if not folder_path:
        return jsonify({'exists': False, 'data': [], 'status': 'error',
                        'motivo': 'sin_ruta', 'message': 'Falta pathToTxt.'})

    txt_file_path, error_response = _un_solo_txt(folder_path)
    if error_response:
        return jsonify(error_response)

    try:
        info = _leer(txt_file_path)
    except OSError as error:
        log.error('check_txt_file no pudo leer %s: %s', txt_file_path, error)
        return jsonify({
            'exists': False,
            'data': [],
            'status': 'error',
            'motivo': 'archivo_ilegible',
            'message': 'No se pudo leer %s: %s' % (txt_file_path, error),
        })

    datos = _comandos(info['texto'])
    lineas = info['texto'].splitlines()

    return jsonify({
        'exists': bool(datos),
        'data': datos,
        'file_name': os.path.basename(txt_file_path),
        'file_path': txt_file_path,
        'size': info['size'],
        'mtime': info['mtime'],
        'sha1': info['sha1'],
        'line_count': len(lineas),
        'last_line': lineas[-1] if lineas else '',
        'en_escritura': _escritor_activo(txt_file_path),
    })


@app.route('/api/check_last_txt_file', methods=['POST'])
def check_last_txt_file():
    """El .txt MÁS RECIENTE de la carpeta (respaldos, para reimprimir)."""
    folder_path = (request.json or {}).get('pathToTxt')
    if not folder_path:
        return jsonify({'exists': False, 'data': [], 'status': 'error',
                        'motivo': 'sin_ruta', 'message': 'Falta pathToTxt.'})

    try:
        files_in_folder = os.listdir(folder_path)
    except OSError as error:
        log.warning('carpeta inaccesible %s: %s', folder_path, error)
        return jsonify({'exists': False, 'data': [], 'status': 'error',
                        'motivo': 'carpeta_inaccesible',
                        'message': 'No se pudo leer la carpeta %s: %s' % (folder_path, error)})

    txt_files = [file for file in files_in_folder if file.endswith('.txt')]
    if not txt_files:
        return jsonify({'exists': False, 'data': [], 'status': 'error',
                        'motivo': 'cero_archivos',
                        'message': 'No se encontró ningún archivo TXT en la carpeta.'})

    last_txt_file = max(txt_files, key=lambda x: os.path.getmtime(os.path.join(folder_path, x)))
    txt_file_path = os.path.join(folder_path, last_txt_file)

    try:
        info = _leer(txt_file_path)
    except OSError as error:
        log.error('check_last_txt_file no pudo leer %s: %s', txt_file_path, error)
        return jsonify({'exists': False, 'data': [], 'status': 'error',
                        'motivo': 'archivo_ilegible',
                        'message': 'No se pudo leer %s: %s' % (txt_file_path, error)})

    datos = _comandos(info['texto'])
    lineas = info['texto'].splitlines()

    return jsonify({
        'exists': bool(datos),
        'data': datos,
        'file_name': last_txt_file,
        'file_path': txt_file_path,
        'size': info['size'],
        'mtime': info['mtime'],
        'sha1': info['sha1'],
        'line_count': len(lineas),
        'last_line': lineas[-1] if lineas else '',
        'en_escritura': _escritor_activo(txt_file_path),
    })


@app.route('/api/clear_txt_file', methods=['POST'])
def clear_txt_file():
    """Archiva el cierre en `backup\\` y deja uno vacío con el mismo nombre.

    ES LA ÚNICA OPERACIÓN DESTRUCTIVA DEL DEMONIO y corre DESPUÉS de imprimir,
    así que si se imprimió un cierre truncado, esto archiva el truncado. Tres
    endurecimientos, ninguno cambia el camino feliz:

    1. `expected_sha1` opcional. El POS puede decir QUÉ archivo cree estar
       archivando; si el que hay no es ese, no se toca nada. Cubre el caso de
       que el VPOS haya escrito otro cierre entre la impresión y el borrado.
    2. Nombre de respaldo ÚNICO. Antes era `<nombre>_<AAAA-MM-DD_HH-MM-SS>.txt`
       con `split('.')[0]`, que parte los nombres con puntos, y con resolución
       de SEGUNDOS: dos cierres en el mismo segundo chocan y en Windows
       `os.rename` FALLA si el destino existe (no sobrescribe como en Linux).
       Ahora lleva microsegundos y, si aun así existe, un sufijo.
    3. `os.rename` ya no puede tumbar el endpoint. Si el VPOS tiene el archivo
       abierto, Windows rechaza el movimiento con PermissionError: antes eso
       era un 500 sin explicación. Ahora se rechaza ANTES, comprobando si hay
       un escritor activo, y el error se devuelve con su motivo.
    """
    payload = request.json or {}
    folder_path = payload.get('pathToTxt')
    expected_sha1 = payload.get('expected_sha1')
    if not folder_path:
        return jsonify({'status': 'error', 'motivo': 'sin_ruta', 'message': 'Falta pathToTxt.'})

    txt_file_path, error_response = _un_solo_txt(folder_path)
    if error_response:
        return jsonify({'status': 'error',
                        'motivo': error_response['motivo'],
                        'message': error_response['message']})

    # No archivar algo que el VPOS todavía está escribiendo.
    if _escritor_activo(txt_file_path) is True:
        log.warning('clear_txt_file: %s sigue abierto por otro proceso', txt_file_path)
        return jsonify({'status': 'error', 'motivo': 'en_escritura',
                        'message': 'El archivo sigue abierto por otro proceso; no se archiva.'})

    if expected_sha1:
        try:
            actual = _leer(txt_file_path)['sha1']
        except OSError as error:
            return jsonify({'status': 'error', 'motivo': 'archivo_ilegible',
                            'message': 'No se pudo leer %s: %s' % (txt_file_path, error)})
        if actual != expected_sha1:
            log.warning('clear_txt_file: sha1 no coincide en %s (esperado %s, hay %s)',
                        txt_file_path, expected_sha1, actual)
            return jsonify({'status': 'error', 'motivo': 'sha1_distinto',
                            'sha1': actual, 'expected_sha1': expected_sha1,
                            'message': 'El archivo no es el que se imprimió; no se archiva.'})

    backup_folder_path = os.path.join(folder_path, 'backup')
    try:
        os.makedirs(backup_folder_path, exist_ok=True)
    except OSError as error:
        return jsonify({'status': 'error', 'motivo': 'backup_inaccesible',
                        'message': 'No se pudo crear %s: %s' % (backup_folder_path, error)})

    base = os.path.splitext(os.path.basename(txt_file_path))[0]
    now = datetime.now().strftime('%Y-%m-%d_%H-%M-%S-%f')
    backup_file_path = os.path.join(backup_folder_path, '%s_%s.txt' % (base, now))
    sufijo = 0
    while os.path.exists(backup_file_path):
        sufijo += 1
        backup_file_path = os.path.join(backup_folder_path, '%s_%s_%d.txt' % (base, now, sufijo))

    try:
        os.rename(txt_file_path, backup_file_path)
    except OSError as error:
        log.error('clear_txt_file no pudo archivar %s: %s', txt_file_path, error)
        return jsonify({'status': 'error', 'motivo': 'no_se_pudo_archivar',
                        'message': 'No se pudo mover %s: %s' % (txt_file_path, error)})

    # Se recrea vacío con el MISMO nombre porque así lleva años funcionando.
    # Es también el origen del caso `varios_archivos`: si el VPOS escribe el
    # siguiente cierre con otro nombre, la carpeta queda con dos .txt. Ver
    # AUDIT.md — decisión pendiente, no se cambia a ciegas.
    try:
        with open(txt_file_path, 'w') as txt_file:
            txt_file.write("")
    except OSError as error:
        log.error('clear_txt_file archivó pero no pudo recrear %s: %s', txt_file_path, error)
        return jsonify({'status': 'error', 'motivo': 'no_se_pudo_recrear',
                        'backup': backup_file_path,
                        'message': 'Se archivó en %s pero no se pudo recrear el vacío: %s'
                                   % (backup_file_path, error)})

    log.info('clear_txt_file archivó %s -> %s', txt_file_path, backup_file_path)
    return jsonify({'status': 'OK', 'backup': backup_file_path})


@app.route('/api/get_lasts_txt', methods=['POST'])
def get_lasts_txt():
    folder_path = (request.json or {}).get('pathToTxt')
    if not folder_path:
        return jsonify({'status': 'error', 'motivo': 'sin_ruta', 'message': 'Falta pathToTxt.'})
    backup_folder_path = os.path.join(folder_path, 'backup')

    try:
        os.makedirs(backup_folder_path, exist_ok=True)
        files = os.listdir(backup_folder_path)
    except OSError as error:
        return jsonify({'status': 'error', 'motivo': 'carpeta_inaccesible',
                        'message': 'No se pudo leer %s: %s' % (backup_folder_path, error)})

    txt_files = [file for file in files if file.endswith('.txt')]
    if not txt_files:
        return jsonify({'status': 'error', 'motivo': 'cero_archivos',
                        'message': 'No TXT files found in the backup folder.'})

    txt_files = sorted(
        txt_files,
        key=lambda x: os.path.getmtime(os.path.join(backup_folder_path, x)),
        reverse=True)[:10]

    result = []
    for file in txt_files:
        file_path = os.path.join(backup_folder_path, file)
        try:
            info = _leer(file_path)
        except OSError as error:
            log.warning('get_lasts_txt saltó %s: %s', file_path, error)
            continue
        result.append({
            'file_name': file,
            'date': datetime.fromtimestamp(info['mtime']).strftime('%Y-%m-%d %H:%M:%S'),
            'sha1': info['sha1'],
            'size': info['size'],
            'commands': _comandos(info['texto']),
        })

    return jsonify(result)


@app.route('/api/restart_service', methods=['POST'])
def restart_service():
    """Reinicia el VPOS (javaw) por la tarea programada RestartVposREST.

    ES LA OPERACIÓN MÁS DESTRUCTIVA DEL DEMONIO: `taskkill /F /IM javaw.exe`
    mata TODOS los javaw de la máquina, sin preguntar y sin gracia. Si el VPOS
    estaba escribiendo un cierre, el archivo queda truncado —una de las causas
    de «cierres incompletos»—; si estaba en medio de un cobro, queda un cobro
    sin respuesta.

    DOS CAMBIOS:

    1. Se comprueba que la tarea EXISTA antes de matar nada. Antes se mataba
       primero y se intentaba arrancar después: si la tarea no estaba, la caja
       se quedaba con el VPOS muerto y sin forma de levantarlo salvo cerrar y
       abrir sesión de Windows. No es hipotético — el .bat que crea la tarea
       (`CreateTaskRestartVposRest.bat`) usa `%TASK_NAME%` y NUNCA define esa
       variable, así que crea la tarea con ese nombre literal en vez de
       `RestartVposREST`, que es el que se invoca aquí.
    2. Se verifica que javaw VUELVA, y se dice la verdad si no vuelve. El POS
       mostraba «servicio reiniciado» pase lo que pase (no mira el `status` de
       la respuesta), así que la cajera leía que todo estaba bien con el VPOS
       caído.
    """
    tarea = 'RestartVposREST'
    try:
        existe = subprocess.run(['schtasks', '/query', '/tn', tarea],
                                capture_output=True, text=True, shell=True)
        if existe.returncode != 0:
            log.error('restart_service abortado: la tarea %s no existe', tarea)
            return jsonify({
                'status': 'error',
                'motivo': 'tarea_inexistente',
                'message': 'No existe la tarea programada %s: no se reinicia nada para no '
                           'dejar el VPOS caído sin forma de levantarlo.' % tarea,
            })

        subprocess.run(['schtasks', '/end', '/tn', tarea],
                       capture_output=True, text=True, shell=True)
        subprocess.run(['taskkill', '/F', '/IM', 'javaw.exe'],
                       capture_output=True, text=True, shell=True)
        time.sleep(2)

        resultado = subprocess.run(['schtasks', '/run', '/tn', tarea],
                                   capture_output=True, text=True, shell=True)
        if resultado.returncode != 0:
            log.error('restart_service: la tarea %s no arrancó: %s', tarea, resultado.stderr)
            return jsonify({'status': 'error', 'motivo': 'no_arranco',
                            'message': 'Error al iniciar la tarea programada: %s' % resultado.stderr})

        # Confirmar que el proceso volvió antes de decir que sí.
        for _ in range(10):
            time.sleep(1)
            listado = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq javaw.exe'],
                                     capture_output=True, text=True, shell=True)
            if 'javaw.exe' in (listado.stdout or ''):
                log.info('restart_service: VPOS reiniciado')
                return jsonify({'status': 'OK', 'message': 'Servicio reiniciado correctamente.'})

        log.error('restart_service: javaw no volvió tras 10 s')
        return jsonify({'status': 'error', 'motivo': 'no_volvio',
                        'message': 'La tarea se lanzó pero javaw.exe no volvió. El VPOS está '
                                   'caído: avise a soporte antes de seguir cobrando.'})

    except Exception as e:
        log.exception('restart_service falló')
        return jsonify({'status': 'error', 'motivo': 'excepcion',
                        'message': 'Error inesperado: %s' % e})


if __name__ == '__main__':
    # `debug=True` dejaba el depurador de Werkzeug expuesto en un equipo de
    # tienda (consola de ejecución de código protegida sólo por un PIN) y
    # activaba el recargador, que arranca un proceso hijo que NSSM no sigue.
    # El servicio sirve tráfico real: no es un entorno de desarrollo.
    app.run(host='127.0.0.1', port=8087, debug=False, threaded=True)

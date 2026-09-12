import time
from datetime import datetime
import os
import subprocess
from flask import Flask, jsonify, request, render_template, send_from_directory
from flask_cors import CORS




app = Flask(__name__)
CORS(app)
app.config['CORS_HEADERS'] = 'Content-Type'



@app.route('/', methods=['GET'])
@app.route('/api/status', methods=['GET'])
def api():
    return jsonify({'status': 'OK'})


@app.route('/api/get_txt_file', methods=['POST'])
def get_txt_file():
    form = request.form.copy()
    local_file=open(request.json['pathToTxt'], 'r')
    data_to_send = ["800" + line.strip('\n') for line in local_file.readlines()]
    data_to_send.append("810Fin del documento.")
    local_file.close()
    print(data_to_send)
    print(jsonify(data_to_send))

    return jsonify(data_to_send)

@app.route('/api/check_txt_file', methods=['POST'])
def check_txt_file():
    """Contenido del ÚNICO .txt de la carpeta, con su identidad y tamaño.

    TRES CAMBIOS (2026-09-12), a raíz de «cierres que salen incompletos»:

    1. Las salidas de error ahora incluyen `exists: False` y `motivo`. Antes
       devolvían sólo {'status','message'}: el POS lee `data.exists`, que salía
       `undefined` (falso), así que su sondeo seguía esperando hasta agotar los
       60 s y la cajera veía «tiempo de espera agotado» cuando el problema real
       era que había CERO o DOS archivos en la carpeta. Un timeout mudo en vez
       del motivo.

       Ojo con el caso de los dos archivos, que no es teórico: `clear_txt_file`
       mueve el cierre al respaldo y RECREA uno vacío con el mismo nombre. Si el
       VPOS escribe el siguiente cierre con OTRO nombre (por fecha, por caja),
       la carpeta pasa a tener dos .txt y este endpoint fallaba en silencio.

    2. Se devuelve `file_name`, `file_path`, `size` y `mtime`. El POS sondea
       este endpoint pasando una CARPETA pero después lee el archivo por otra
       vía (`get_txt_file` con la ruta que le dio el VPOS), así que validaba una
       cosa y leía otra. Con la ruta resuelta aquí puede leer exactamente lo que
       comprobó.

    3. `size`/`mtime` permiten detectar un archivo aún EN ESCRITURA. El datáfono
       escribe el cierre de forma asíncrona y el manual de Megasoft
       (MAET-VPOSW-00) no ofrece tamaño, marca de fin ni confirmación: un
       archivo recién creado ya «existe» desde su primer byte. El POS compara
       lecturas consecutivas y sólo acepta el archivo cuando deja de cambiar.

    Todo lo añadido es ADITIVO: `exists` y `data` conservan su significado, así
    que un POS viejo contra un demonio nuevo se comporta igual que antes.
    """
    folder_path = request.json['pathToTxt']

    try:
        files_in_folder = os.listdir(folder_path)
    except OSError as error:
        return jsonify({
            'exists': False,
            'data': [],
            'status': 'error',
            'motivo': 'carpeta_inaccesible',
            'message': 'No se pudo leer la carpeta %s: %s' % (folder_path, error),
        })

    txt_files = [file for file in files_in_folder if file.endswith('.txt')]

    if len(txt_files) != 1:
        return jsonify({
            'exists': False,
            'data': [],
            'status': 'error',
            'motivo': 'cero_archivos' if not txt_files else 'varios_archivos',
            'archivos': txt_files,
            'message': 'No se encontró un único archivo TXT en la carpeta. '
                       'Encontrados: %d (%s)' % (len(txt_files), ', '.join(txt_files) or 'ninguno'),
        })

    txt_file_path = os.path.join(folder_path, txt_files[0])

    try:
        estado = os.stat(txt_file_path)
        with open(txt_file_path, 'r') as remote_file:
            lines = remote_file.readlines()
    except OSError as error:
        return jsonify({
            'exists': False,
            'data': [],
            'status': 'error',
            'motivo': 'archivo_ilegible',
            'message': 'No se pudo leer %s: %s' % (txt_file_path, error),
        })

    # Un archivo vacío o sólo con espacios NO es un cierre: se informa como
    # inexistente para que el POS siga esperando en vez de imprimir nada.
    if "".join(lines).strip():
        data_to_send = ["800" + line.strip('\n') for line in lines]
        data_to_send.append("810Fin del documento.")
    else:
        data_to_send = []

    return jsonify({
        'exists': bool(data_to_send),
        'data': data_to_send,
        'file_name': txt_files[0],
        'file_path': txt_file_path,
        'size': estado.st_size,
        'mtime': estado.st_mtime,
    })

@app.route('/api/check_last_txt_file', methods=['POST'])
def check_last_txt_file():
    form = request.form.copy()
    folder_path = request.json['pathToTxt']
    # Obtener lista de archivos en la carpeta
    files_in_folder = os.listdir(folder_path)

    # Filtrar archivos que sean archivos de texto
    txt_files = [file for file in files_in_folder if file.endswith('.txt')]

    if not txt_files:
        return jsonify({'status': 'error', 'message': 'No se encontró ningún archivo TXT en la carpeta.'})

    # Obtener el archivo .txt más reciente por fecha de modificación
    last_txt_file = max(txt_files, key=lambda x: os.path.getmtime(os.path.join(folder_path, x)))
    txt_file_path = os.path.join(folder_path, last_txt_file)

    # Abrir el archivo TXT y leer su contenido
    with open(txt_file_path, 'r') as remote_file:
        data_to_send = ["800" + line.strip('\n') for line in remote_file.readlines()]
        data_to_send.append("810Fin del documento.")

    return jsonify({
        'exists': bool(data_to_send),
        'data': data_to_send,
        'file_name': last_txt_file
    })

@app.route('/api/clear_txt_file', methods=['POST'])
def clear_txt_file():
    form = request.form.copy()
    folder_path = request.json['pathToTxt']
    files_in_folder = os.listdir(folder_path)
    txt_files = [file for file in files_in_folder if file.endswith('.txt')]
    if len(txt_files) != 1:
        return jsonify({'status': 'error', 'message': 'No se encontró un único archivo TXT en la carpeta.'})

    txt_file_path = os.path.join(folder_path, txt_files[0])

    # Crear la carpeta de backup si no existe
    backup_folder_path = os.path.join(folder_path, 'backup')
    try:
        os.mkdir(backup_folder_path)
    except IOError:
        pass

    # Copiar el archivo a la carpeta de backup con el nombre de la fecha
    now = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    backup_file_path = os.path.join(backup_folder_path, f"{txt_files[0].split('.')[0]}_{now}.txt")
    os.rename(txt_file_path, backup_file_path)

    # Vaciar el contenido del archivo
    with open(txt_file_path, 'w') as txt_file:
        txt_file.write("")
    return jsonify({'status': 'OK'})


@app.route('/api/get_lasts_txt', methods=['POST'])
def get_lasts_txt():
    folder_path = request.json['pathToTxt']
    backup_folder_path = os.path.join(folder_path, 'backup')

    try:
        os.mkdir(backup_folder_path)
    except IOError:
        pass

    files = os.listdir(backup_folder_path)
    txt_files = [file for file in files if file.endswith('.txt')]

    if not txt_files:
        return jsonify({'status': 'error', 'message': 'No TXT files found in the backup folder.'})

    # Get the last 7 files sorted by modification date
    txt_files = sorted(txt_files, key=lambda x: os.path.getmtime(os.path.join(backup_folder_path, x)), reverse=True)[:10]

    result = []
    for file in txt_files:
        file_path = os.path.join(backup_folder_path, file)
        modification_time = os.path.getmtime(file_path)
        with open(file_path, 'r') as f:
            commands = ["800" + line.strip('\n') for line in f.readlines()]
            commands.append("810Fin del documento.")
        result.append({
            'file_name': file,
            'date': datetime.fromtimestamp(modification_time).strftime('%Y-%m-%d %H:%M:%S'),
            'commands': commands
        })

    return jsonify(result)

@app.route('/api/restart_service', methods=['POST'])
def restart_service():
    try:
        # Intentar detener la tarea programada si está corriendo
        subprocess.run(['schtasks', '/end', '/tn', 'RestartVposREST'], capture_output=True, text=True, shell=True)
        
        # Terminate javaw.exe directly using taskkill
        subprocess.run(['taskkill', '/F', '/IM', 'javaw.exe'], capture_output=True, text=True, shell=True)
        
        # Esperar un momento para asegurar que el proceso termine
        time.sleep(2)

        # Ejecutar la tarea programada RestartVposREST para iniciar RestartVposREST
        result = subprocess.run(['schtasks', '/run', '/tn', 'RestartVposREST'], capture_output=True, text=True, check=True)
        
         
        # Verificar que la tarea se ejecutó correctamente
        if result.returncode == 0:
            return jsonify({'status': 'OK', 'message': 'Servicio reiniciado correctamente.'})
        else:
            return jsonify({'status': 'error', 'message': 'Error al iniciar la tarea programada.'})
            
    except subprocess.CalledProcessError as e:
        return jsonify({'status': 'error', 'message': f'Error al ejecutar el script: {e.stderr}'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Error inesperado: {str(e)}'})



if __name__ == '__main__':
    app.run(debug=True, port=8087)
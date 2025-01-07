import time
from datetime import datetime
import os

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
    data_to_send = ["80 " + line.strip('\n') for line in local_file.readlines()]
    local_file.close()
    print(data_to_send)
    print(jsonify(data_to_send))

    return jsonify(data_to_send)

@app.route('/api/check_txt_file', methods=['POST'])
def check_txt_file():

    form = request.form.copy()
    folder_path = request.json['pathToTxt']
    # Obtener lista de archivos en la carpeta remota
    files_in_folder = os.listdir(folder_path)

    # Filtrar archivos que sean archivos de texto
    txt_files = [file for file in files_in_folder if file.endswith('.txt')]

    # Verificar si hay exactamente un archivo de texto en la carpeta
    if len(txt_files) != 1:
        return jsonify({'status': 'error', 'message': 'No se encontró un único archivo TXT en la carpeta.'})

    # Construir la ruta completa del archivo TXT
    txt_file_path = os.path.join(folder_path, txt_files[0])

    # Abrir el archivo TXT y leer su contenido
    remote_file = open(txt_file_path, 'r')
    data_to_send = ["80 " + line.strip('\n') for line in remote_file.readlines()]
    remote_file.close()

    return jsonify({
        'exists': bool(data_to_send),
        'data': data_to_send
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
            commands = ["80 " + line.strip('\n') for line in f.readlines()]
        result.append({
            'file_name': file,
            'date': datetime.fromtimestamp(modification_time).strftime('%Y-%m-%d %H:%M:%S'),
            'commands': commands
        })

    return jsonify(result)

@app.route('/api/restart_service', methods=['POST'])
def restart_service():
    try:
        import win32serviceutil
        win32serviceutil.RestartService('Vpos')
    except Exception as e:
        return jsonify({'status': 'OK', 'message': str(e)})
    time.sleep(10)

    return jsonify({'status': 'OK'})



if __name__ == '__main__':
    app.run(debug=True, port=8087)
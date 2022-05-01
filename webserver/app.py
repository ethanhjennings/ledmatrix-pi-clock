import json

from flask import Flask, send_file, send_from_directory, g
from flask_socketio import SocketIO, emit

app = Flask(__name__)
socketio = SocketIO(app)# logger=True, engineio_logger=True, log_output=True)

@app.route('/')
def root():
    return send_file('html/index.html')

@app.route('/js/<path:path>')
def static_js(path):
    return send_from_directory('js', path)

@socketio.on('connect')
def handle_connect(auth):
    emit('get_state', broadcast=True)

@socketio.on('display_state')
def handle_enable(data):
    emit('display_state', data, broadcast=True)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=80)

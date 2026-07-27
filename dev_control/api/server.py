import os
import sys
from flask import Flask, jsonify, request

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import config
from api.routes.devices import devices_bp
from api.routes.control import control_bp
from api.routes.hot_reload import hot_reload_bp

app = Flask(__name__)

@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS'
    return response

# Register Blueprints
app.register_blueprint(devices_bp)
app.register_blueprint(control_bp)
app.register_blueprint(hot_reload_bp)

@app.route('/health', methods=['GET'])
def health():
    return {"status": "healthy", "service": "nmap-dev-api", "port": config.API_PORT}

if __name__ == '__main__':
    print(f"🚀 Starting Dev Control API Server on port {config.API_PORT}...")
    app.run(host=config.HOST, port=config.API_PORT, debug=False, threaded=True)

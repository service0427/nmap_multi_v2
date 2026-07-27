import os
import sys
from flask import Flask, render_template

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import config

app = Flask(__name__, 
            template_folder=os.path.join(BASE_DIR, "web", "templates"),
            static_folder=os.path.join(BASE_DIR, "web", "static"))

@app.route('/')
@app.route('/table')
@app.route('/grid')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    print(f"🚀 Starting Dev Control Web Dashboard on port {config.WEB_PORT}...")
    app.run(host=config.HOST, port=config.WEB_PORT, debug=False, threaded=True)

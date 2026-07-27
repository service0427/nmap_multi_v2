import os

# Dev Control System Configuration
WEB_PORT = 5001
API_PORT = 5555
HOST = "0.0.0.0"

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")
DEVICES_DIR = os.path.join(LOGS_DIR, "devices")

# Central API Server
API_SERVER = "100.65.34.98:8013"

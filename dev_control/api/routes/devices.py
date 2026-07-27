import sys
import os
import subprocess
from flask import Blueprint, jsonify, Response

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)

from services.device_service import DeviceService
from adb import ADBManager

devices_bp = Blueprint('devices', __name__)

@devices_bp.route('/api/v1/devices', methods=['GET'])
def get_devices():
    """Returns list of connected devices and their current states."""
    states = DeviceService.get_all_device_states()
    
    # Calculate statistics
    total = len(states)
    running = sum(1 for s in states if s["is_running"])
    idle = sum(1 for s in states if "IDLE" in s["step"])
    cooldown = sum(1 for s in states if "COOLDOWN" in s["step"] or "PENALTY" in s["step"])
    
    return jsonify({
        "status": "ok",
        "timestamp": states[0]["last_active"] if states else "-",
        "stats": {
            "total": total,
            "running": running,
            "idle": idle,
            "cooldown": cooldown
        },
        "devices": states
    })

@devices_bp.route('/api/v1/screen/<device_id>', methods=['GET'])
def get_device_screen(device_id):
    """Returns real-time PNG screencap image directly from ADB."""
    try:
        cmd = ["adb", "-s", device_id, "exec-out", "screencap", "-p"]
        img_bytes = subprocess.check_output(cmd, timeout=3)
        return Response(img_bytes, mimetype='image/png')
    except Exception as e:
        # Fallback 1x1 transparent PNG if offline
        return Response(b'', mimetype='image/png')

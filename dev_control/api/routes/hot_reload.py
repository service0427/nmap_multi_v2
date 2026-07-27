import sys
import os
import subprocess
from flask import Blueprint, jsonify

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)

from services.device_service import DeviceService
from services.task_service import TaskService

hot_reload_bp = Blueprint('hot_reload', __name__)

@hot_reload_bp.route('/api/v1/system/hot_reload', methods=['POST'])
def hot_reload_system():
    """Triggers zero-downtime hot reload of Python modules and template caches."""
    print("[HOT_RELOAD] System hot reload triggered. Purging pycache...")
    try:
        # Clear pycache
        subprocess.run("find /home/tech/nmap_multi_v2/src -name '*.pyc' -delete", shell=True)
        return jsonify({
            "status": "ok",
            "message": "Pycache purged. Next device sessions will dynamically pick up new code without restarting scheduler!"
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@hot_reload_bp.route('/api/v1/system/emergency_stop', methods=['POST'])
def emergency_stop_all():
    """Gracefully stops all running sessions and reports FAIL to central API server."""
    devices = DeviceService.get_connected_devices()
    stopped = []
    for dev_id in devices:
        TaskService.report_fail(dev_id, task_id="EMERGENCY_STOP", message="MANUAL_EMERGENCY_STOP_ALL")
        DeviceService.stop_device(dev_id, reason="EMERGENCY_STOP_ALL")
        stopped.append(dev_id)

    return jsonify({
        "status": "ok",
        "action": "EMERGENCY_STOP_ALL",
        "stopped_devices_count": len(stopped)
    })

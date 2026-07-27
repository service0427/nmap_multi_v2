import sys
import os
from flask import Blueprint, request, jsonify

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)

from services.device_service import DeviceService
from services.task_service import TaskService

control_bp = Blueprint('control', __name__)

@control_bp.route('/api/v1/device/control', methods=['POST'])
def control_device():
    """Handles single-device control actions: stop, restart, mute, clear_cooldown."""
    data = request.get_json() or {}
    device_id = data.get("device_id")
    action = data.get("action") # stop, restart, mute, clear_cooldown

    if not device_id or not action:
        return jsonify({"status": "error", "message": "device_id and action are required"}), 400

    print(f"[CONTROL_API] Received action '{action}' for target device: {device_id}")

    if action == "start":
        DeviceService.start_device(device_id)
    elif action == "pause":
        DeviceService.pause_device(device_id)
    elif action == "stop":
        task_id = data.get("task_id", "DEV_STOP")
        TaskService.report_fail(device_id, task_id, message="MANUAL_DEV_STOP")
        DeviceService.stop_device(device_id, reason="MANUAL_DEV_STOP")
    elif action == "restart":
        DeviceService.restart_device(device_id)
    elif action == "mute":
        DeviceService.mute_device(device_id)
    elif action == "clear_cooldown":
        DeviceService.clear_cooldown(device_id)
    else:
        return jsonify({"status": "error", "message": f"Unknown action '{action}'"}), 400

    return jsonify({
        "status": "ok",
        "device_id": device_id,
        "action": action,
        "result": "SUCCESS"
    })

@control_bp.route('/api/v1/device/bulk_control', methods=['POST'])
def bulk_control_devices():
    """Handles bulk device control actions."""
    data = request.get_json() or {}
    device_ids = data.get("device_ids", [])
    action = data.get("action")

    if not device_ids or not action:
        return jsonify({"status": "error", "message": "device_ids list and action are required"}), 400

    results = {}
    for dev_id in device_ids:
        if action == "stop":
            DeviceService.stop_device(dev_id)
        elif action == "restart":
            DeviceService.restart_device(dev_id)
        elif action == "mute":
            DeviceService.mute_device(dev_id)
        elif action == "clear_cooldown":
            DeviceService.clear_cooldown(dev_id)
        results[dev_id] = "OK"

    return jsonify({
        "status": "ok",
        "action": action,
        "processed_count": len(device_ids),
        "results": results
    })

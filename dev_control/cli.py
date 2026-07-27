#!/usr/bin/env python3
import sys
import os
import argparse
import urllib.request
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src", "lib"))
sys.path.insert(0, BASE_DIR)

from services.device_service import DeviceService
from services.task_service import TaskService

def main():
    parser = argparse.ArgumentParser(description="Nmap Multi V2 Dev Control CLI")
    parser.add_argument("--device", required=True, help="Target device serial number")
    parser.add_argument("--action", required=True, choices=["start", "pause", "stop", "restart", "mute", "clear_cooldown"], help="Action to execute")
    args = parser.parse_args()

    dev_id = args.device
    action = args.action

    print(f"[*] Executing CLI action '{action}' on device [{dev_id}]...")

    try:
        # Attempt via local Dev REST API on port 5555
        url = "http://127.0.0.1:5555/api/v1/device/control"
        payload = json.dumps({"device_id": dev_id, "action": action}).encode('utf-8')
        req = urllib.request.Request(url, data=payload, method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            res_json = json.loads(resp.read().decode('utf-8'))
            print(f"[✓] REST API Execution Success: {res_json}")
            return
    except Exception:
        # Direct DeviceService execution fallback
        print(f"[*] Dev API offline. Executing via direct DeviceService...")

    if action == "start":
        DeviceService.start_device(dev_id)
    elif action == "pause":
        DeviceService.pause_device(dev_id)
    elif action == "stop":
        TaskService.report_fail(dev_id, "DEV_CLI_STOP", message="MANUAL_CLI_STOP")
        DeviceService.stop_device(dev_id, reason="MANUAL_CLI_STOP")
    elif action == "restart":
        DeviceService.restart_device(dev_id)
    elif action == "mute":
        DeviceService.mute_device(dev_id)
    elif action == "clear_cooldown":
        DeviceService.clear_cooldown(dev_id)
    
    print(f"[✓] Direct action '{action}' completed for [{dev_id}].")

if __name__ == "__main__":
    main()

import os
import sys
import json
import subprocess

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
import config

class TaskService:
    @staticmethod
    def report_fail(device_id, task_id, message="DEV_CONTROL_MANUAL_CANCEL"):
        url = f"http://{config.API_SERVER}/api/v1/report_result"
        payload = {
            "task_id": task_id,
            "device_id": device_id,
            "status": "FAIL",
            "message": message
        }
        try:
            res = subprocess.run(
                ["curl", "-s", "-X", "POST", url, "-H", "Content-Type: application/json", "-d", json.dumps(payload)],
                capture_output=True, text=True, timeout=3
            )
            return True
        except Exception as e:
            print(f"[TASK_SERVICE] Error reporting fail: {e}")
            return False

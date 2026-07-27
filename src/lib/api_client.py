#!/usr/bin/env python3
import json
import urllib.request
import urllib.error
import os
from datetime import datetime

import manifest

try:
    global_cfg = manifest.load_global_config()
    API_SERVER = global_cfg.get("API_SERVER", "114.207.112.245:8013")
except:
    API_SERVER = "114.207.112.245:8013"

def _log_api_backup(endpoint, payload, response_str, device_id="SYSTEM"):
    """Replicates V1 log_api_backup by writing transaction logs to api_backup/ folder."""
    try:
        today = datetime.now().strftime("%Y%m%d")
        backup_dir = f"/home/tech/nmap_multi_v1/api_backup/{today}/{device_id}"
        os.makedirs(backup_dir, exist_ok=True)
        backup_file = os.path.join(backup_dir, "api.log")
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        task_id = payload.get("task_id", "N/A") if isinstance(payload, dict) else "N/A"
        
        with open(backup_file, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] [Task: {task_id}]\n")
            f.write(f"  - REQ: {endpoint} -> {json.dumps(payload, ensure_ascii=False)}\n")
            f.write(f"  - RES: {response_str}\n")
            f.write("------------------------------------------------------------\n")
            
        try:
            os.chmod(backup_file, 0o666)
        except: pass
    except:
        pass

def _send_post(endpoint, payload, timeout=5):
    """Internal helper to execute a POST request to the API server."""
    url = f"http://{API_SERVER}{endpoint}"
    data = json.dumps(payload).encode('utf-8')
    now_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{now_str}] [API_REQ] {endpoint} -> {json.dumps(payload, ensure_ascii=False)}")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            res_body = response.read().decode('utf-8')
            http_code = response.status
            print(f"[{now_str}] [API_RES] {res_body}\nHTTP_CODE:{http_code}")
            return True, res_body
    except Exception as e:
        print(f"[{now_str}] [API_RES] FAIL: {e}")
        return False, str(e)

def request_task(device_id):
    """Requests a routing and laundering task for a device from the API server."""
    payload = {"device_id": device_id}
    success, response = _send_post("/api/v1/request_task", payload)
    _log_api_backup("/api/v1/request_task", payload, response, device_id=device_id)
    if success:
        try:
            return json.loads(response)
        except Exception as e:
            return {"status": "ERROR", "message": f"JSON parse error: {e}"}
    return {"status": "ERROR", "message": response}

def update_status(task_id, device_id, status, real_ip="LOCAL_WAN", message=""):
    """Sends a live status update for a device during driving simulation."""
    payload = {
        "task_id": int(task_id) if str(task_id).isdigit() else task_id,
        "device_id": device_id,
        "status": status,
        "real_ip": real_ip,
        "message": message
    }
    success, response = _send_post("/api/v1/update_status", payload)
    _log_api_backup("/api/v1/update_status", payload, response, device_id=device_id)
    return success, response

def report_result(task_id, device_id, status, reason, payload_extra=None):
    """Reports the final session execution status and parameters to the server."""
    payload = {
        "task_id": int(task_id) if str(task_id).isdigit() else task_id,
        "device_id": device_id,
        "status": status,
        "reason": reason
    }
    if isinstance(payload_extra, dict):
        payload.update(payload_extra)
        
    success, response = _send_post("/api/v1/report_result", payload)
    _log_api_backup("/api/v1/report_result", payload, response, device_id=device_id)
    return success, response

def send_lte_usage(name, upload_bytes, download_bytes, ip_addr):
    """Sends active LTE modem upload/download traffic usage data to telemetry server."""
    payload = {
        "name": name,
        "upload": upload_bytes,
        "download": download_bytes,
        "ip": ip_addr
    }
    success, response = _send_post("/api/v1/lte_usage", payload)
    _log_api_backup("/api/v1/lte_usage", payload, response, device_id=name)
    return success, response

#!/usr/bin/env python3
import os
import subprocess
import time
import threading
import socket
import json
from flask import Flask, Response, render_template_string, request, jsonify

app = Flask(__name__)

# --- CONFIGURATION ---
PORT = 5000
REFRESH_INTERVAL = 0.12  # 약 8fps

def get_connected_devices_count():
    try:
        output = subprocess.check_output(["adb", "devices"], timeout=3).decode("utf-8")
        lines = output.strip().split("\n")[1:]
        count = sum(1 for line in lines if line.strip() and "device" in line)
        return max(10, count)
    except:
        return 10

MAX_SLOTS = get_connected_devices_count()
V2_ROOT = "/home/tech/nmap_multi_v2"
LOG_BASE_DIR = os.path.join(V2_ROOT, "logs")

import sys
sys.path.insert(0, os.path.join(V2_ROOT, "src", "lib"))
import manifest

device_slots = [None] * MAX_SLOTS
diag_cache = {}

TEMPLATE_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "monitor.html")

def get_html_template():
    try:
        with open(TEMPLATE_FILE_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error loading template: {e}"

def get_device_diagnostics(serial):
    info = {
        "status": "IDLE",
        "ip": "N/A",
        "temp": "??",
        "battery": "??",
        "latest_log": "-",
        "current_task": None,
        "disabled": False,
        "usb_path": "N/A",
        "subnet": manifest.get_device_subnet(serial)
    }
    
    # Check working status of V2 tasks (proxy_manager.py)
    is_proc_running = False
    try:
        for pid in os.listdir('/proc'):
            if not pid.isdigit(): continue
            try:
                with open(os.path.join('/proc', pid, 'cmdline'), 'r') as pf:
                    cmd = pf.read().replace('\x00', ' ')
                    if 'proxy_manager.py' in cmd and f'--device {serial}' in cmd:
                        if 'sync_gui_control' not in cmd:
                            is_proc_running = True
                            break
            except: pass
    except: pass

    if is_proc_running:
        info["status"] = "WORKING"
    else:
        info["status"] = "IDLE"
        try:
            task_info_path = os.path.join(LOG_BASE_DIR, "devices", serial, "current_task.json")
            if os.path.exists(task_info_path):
                with open(task_info_path, 'r') as f:
                    cdata = json.load(f)
                    cstatus = cdata.get("status")
                    if cstatus in ["IP_COOLDOWN", "COOLDOWN", "PENALTY", "UNAUTHORIZED"]:
                        info["status"] = cstatus
        except: pass

    # Get battery info
    try:
        batt_raw = subprocess.check_output(["adb", "-s", serial, "shell", "dumpsys battery"], timeout=5).decode()
        for line in batt_raw.splitlines():
            if "level:" in line: info["battery"] = line.split(":")[1].strip()
            if "temperature:" in line: info["temp"] = int(line.split(":")[1].strip()) / 10
    except: pass

    task_data = {
        "dest_name": "Unknown",
        "dest_id": "",
        "start_ts": 0,
        "target_sec": 0,
        "total_dist_km": 0.0,
        "remaining_dist_km": 0.0,
        "avg_speed_kmh": 0.0,
        "status": "IDLE"
    }
    
    latest_session_dir = None
    latest_date_str = None
    try:
        dev_log_dir = os.path.join(LOG_BASE_DIR, "macro_car")
        if os.path.exists(dev_log_dir):
            dates = sorted([d for d in os.listdir(dev_log_dir) if d.isdigit()], reverse=True)
            if dates:
                latest_date_str = dates[0]
                date_dir = os.path.join(dev_log_dir, latest_date_str)
                # Check new structure: macro_car/date/serial/hms_destid
                new_s_path = os.path.join(date_dir, serial)
                if os.path.exists(new_s_path):
                    try:
                        sub_sessions = sorted([ss for ss in os.listdir(new_s_path) if "_" in ss], reverse=True)
                        if sub_sessions:
                            latest_session_dir = os.path.join(new_s_path, sub_sessions[0])
                            info["latest_log"] = f"{latest_date_str}/{serial}/{sub_sessions[0]}"
                            parts = sub_sessions[0].split("_")
                            if len(parts) >= 2:
                                task_data["dest_id"] = parts[1]
                    except: pass
                
                # Fallback to old structure if not resolved: macro_car/date/hms_destid/serial
                if not latest_session_dir:
                    sessions = sorted([s for s in os.listdir(date_dir) if "_" in s], reverse=True)
                    for s in sessions:
                        s_path = os.path.join(date_dir, s, serial)
                        if os.path.exists(s_path):
                            latest_session_dir = s_path
                            info["latest_log"] = f"{latest_date_str}/{s}"
                            parts = s.split("_")
                            if len(parts) >= 2:
                                task_data["dest_id"] = parts[1]
                            break
    except Exception as e:
        print(f"Error resolving latest session dir: {e}", flush=True)

    session_status = None
    if latest_session_dir and os.path.exists(latest_session_dir):
        summary_path = os.path.join(latest_session_dir, "session_summary.json")
        if os.path.exists(summary_path):
            try:
                with open(summary_path, 'r') as f:
                    sdata = json.load(f)
                    info["ip"] = sdata.get("real_ip", info["ip"])
                    session_status = sdata.get("status", None)
                    if sdata.get("total_distance_km"):
                        task_data["total_dist_km"] = sdata.get("total_distance_km")
            except: pass

    try:
        task_info_path = os.path.join(LOG_BASE_DIR, "devices", serial, "current_task.json")
        if os.path.exists(task_info_path):
            with open(task_info_path, 'r') as f:
                cdata = json.load(f)
                for k, v in cdata.items():
                    if v is not None:
                        task_data[k] = v
                info["ip"] = cdata.get("real_ip", info["ip"])
                
                # Map V2 current_task keys to dashboard keys
                if cdata.get("distance_km") is not None:
                    task_data["total_dist_km"] = cdata.get("distance_km")
                if cdata.get("total_target_sec") is not None:
                    task_data["target_sec"] = cdata.get("total_target_sec")
                if cdata.get("simulated_speed") is not None:
                    task_data["avg_speed_kmh"] = cdata.get("simulated_speed")
                if cdata.get("dest_name") is not None:
                    task_data["dest_name"] = cdata.get("dest_name")
    except: pass

    # In V2, parse gps_simulation.log for real-time progress details
    if latest_session_dir and os.path.exists(latest_session_dir):
        gps_log_path = os.path.join(latest_session_dir, "gps_simulation.log")
        if os.path.exists(gps_log_path):
            try:
                with open(gps_log_path, 'r', encoding='utf-8', errors='ignore') as f:
                    gps_lines = f.readlines()
                
                distances = []
                for line in gps_lines:
                    if "Distance:" in line:
                        try:
                            # Extract distance value (e.g. Distance: 14.19 km)
                            d_val = float(line.split("Distance:")[-1].split("km")[0].strip())
                            distances.append(d_val)
                        except: pass
                
                if distances:
                    task_data["total_dist_km"] = distances[0]
                    task_data["remaining_dist_km"] = distances[-1]
            except: pass
            
        # Parse start_ts from driving_start_time if present
        if task_data.get("driving_start_time"):
            try:
                # e.g. "14:27:07" -> convert to UNIX timestamp for today
                from datetime import datetime, date
                time_part = datetime.strptime(task_data["driving_start_time"], "%H:%M:%S").time()
                dt = datetime.combine(date.today(), time_part)
                task_data["start_ts"] = int(dt.timestamp())
            except: pass

    # Parse live task state transition from execution.log
    if latest_session_dir and os.path.exists(latest_session_dir):
        exec_log_path = os.path.join(latest_session_dir, "execution.log")
        if os.path.exists(exec_log_path):
            try:
                with open(exec_log_path, 'r', encoding='utf-8', errors='ignore') as f:
                    log_lines = f.readlines()
                for line in log_lines:
                    if "Transitioning to ->" in line:
                        task_data["status"] = line.split("Transitioning to ->")[-1].strip()
                    elif "Waiting for lock on subnet" in line:
                        task_data["status"] = "LOCK_WAITING"
                    elif "Subnet Lock acquired" in line:
                        task_data["status"] = "LOCK_ACQUIRED"
                    elif "Subnet Lock released" in line:
                        task_data["status"] = "DRIVING_WAIT"
            except: pass

    is_working = (info["status"] == "WORKING")
    log_has_success = False
    
    if latest_session_dir and os.path.exists(latest_session_dir):
        exec_log_path = os.path.join(latest_session_dir, "execution.log")
        if os.path.exists(exec_log_path):
            try:
                with open(exec_log_path, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()[-20:]
                for line in lines:
                    if "SUCCESS" in line or "SUCCESSFUL" in line:
                        log_has_success = True
                        break
            except: pass

    if is_working:
        detailed_status = task_data.get("status", "DRIVING")
        if detailed_status in ["IDLE", "SUCCESS", "ARRIVED", "Unknown", ""]:
            detailed_status = "DRIVING"
        info["status"] = detailed_status
        task_data["status"] = detailed_status
        info["current_task"] = task_data
    else:
        if session_status == "ARRIVED" or log_has_success:
            info["status"] = "SUCCESS"
            task_data["status"] = "SUCCESS"
            info["current_task"] = task_data
        else:
            info["status"] = "IDLE"
            info["current_task"] = None

    info["cooldown_info"] = None
    info["usb_path"] = manifest.get_device_usb_port(serial)

    if manifest.is_device_excluded(serial):
        info["disabled"] = True
        if info["status"] not in ["WORKING", "DRIVING"]:
            info["status"] = "DISABLED"
            
    return info

def refresh_device_slots():
    global device_slots, MAX_SLOTS
    try:
        output = subprocess.check_output(["adb", "devices", "-l"], timeout=5).decode("utf-8")
        lines = output.strip().split("\n")[1:]
        current_connected = {}
        usb_mapping_updates = {}
        for line in lines:
            if not line.strip() or "device" not in line: continue
            parts = line.split()
            serial = parts[0]
            model = "Unknown"
            usb_path = "N/A"
            for p in parts:
                if p.startswith("model:"): model = p.split(":")[1]
                if p.startswith("usb:"): usb_path = p
            current_connected[serial] = model
            if usb_path != "N/A":
                usb_mapping_updates[serial] = usb_path

        manifest_data = manifest.load_manifest()
        
        # Update manifest_data with fresh USB mappings if they differ
        usb_changed = False
        for serial, usb_path in usb_mapping_updates.items():
            if serial in manifest_data:
                if manifest_data[serial].get("usb_port") != usb_path:
                    manifest_data[serial]["usb_port"] = usb_path
                    usb_changed = True
        if usb_changed:
            manifest.save_manifest(manifest_data)

        # Get list of device serials in display order
        order_list = manifest.get_ordered_devices()
        
        MAX_SLOTS = len(order_list)
        while len(device_slots) < MAX_SLOTS:
            device_slots.append(None)
        if len(device_slots) > MAX_SLOTS:
            device_slots = device_slots[:MAX_SLOTS]

        for i, serial in enumerate(order_list):
            is_excluded = manifest.is_device_excluded(serial)
            usb_path = manifest.get_device_usb_port(serial)
            
            if serial in current_connected:
                diag = get_device_diagnostics(serial)
                device_slots[i] = {
                    "id": serial,
                    "model": current_connected[serial],
                    "offline": False,
                    **diag
                }
            else:
                device_slots[i] = {
                    "id": serial,
                    "model": "Unknown",
                    "offline": True,
                    "status": "DISABLED" if is_excluded else "OFFLINE",
                    "ip": "N/A",
                    "temp": "??",
                    "battery": "??",
                    "latest_log": "-",
                    "current_task": None,
                    "disabled": is_excluded,
                    "usb_path": usb_path,
                    "subnet": manifest.get_device_subnet(serial)
                }
    except Exception as e:
        print(f"Error in refresh_device_slots: {e}", flush=True)

def diag_background_thread():
    while True:
        refresh_device_slots()
        time.sleep(10)

refresh_device_slots()
threading.Thread(target=diag_background_thread, daemon=True).start()

@app.route('/')
def index():
    device_id = request.args.get('device_id', '').strip()
    hostname = socket.gethostname()
    return render_template_string(get_html_template(), slots=device_slots, MAX_SLOTS=MAX_SLOTS, hostname=hostname, target_device_id=device_id)

@app.route('/status')
def status():
    return jsonify({"slots": device_slots})

@app.route('/api/toggle_device', methods=['POST'])
def toggle_device():
    try:
        data = request.get_json() or {}
        serial = data.get("device_id")
        if not serial:
            return jsonify({"status": "error", "message": "Missing device_id"}), 400
        
        is_excluded = manifest.toggle_device_exclusion(serial)
        state = "DISABLED" if is_excluded else "ENABLED"
        
        refresh_device_slots()
        return jsonify({"status": "success", "state": state, "excluded": [serial] if is_excluded else []})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/click/<dev_id>')
def click(dev_id):
    x_pct = float(request.args.get('x_pct', 0))
    y_pct = float(request.args.get('y_pct', 0))
    try:
        out = subprocess.check_output(["adb", "-s", dev_id, "shell", "wm size"], timeout=5).decode("utf-8")
        size = out.split(":")[-1].strip().split("x")
        w, h = int(size[0]), int(size[1])
        tx, ty = int(w * x_pct), int(h * y_pct)
        subprocess.Popen(["adb", "-s", dev_id, "shell", "input", "tap", str(tx), str(ty)])
    except: pass
    return "OK"

@app.route('/swipe/<dev_id>')
def swipe(dev_id):
    x1_pct = float(request.args.get('x1_pct', 0))
    y1_pct = float(request.args.get('y1_pct', 0))
    x2_pct = float(request.args.get('x2_pct', 0))
    y2_pct = float(request.args.get('y2_pct', 0))
    try:
        out = subprocess.check_output(["adb", "-s", dev_id, "shell", "wm size"], timeout=5).decode("utf-8")
        size = out.split(":")[-1].strip().split("x")
        w, h = int(size[0]), int(size[1])
        tx1, ty1 = int(w * x1_pct), int(h * y1_pct)
        tx2, ty2 = int(w * x2_pct), int(h * y2_pct)
        subprocess.Popen(["adb", "-s", dev_id, "shell", "input", "swipe", str(tx1), str(ty1), str(tx2), str(ty2), "300"])
    except: pass
    return "OK"

@app.route('/key/<dev_id>')
def key(dev_id):
    code = request.args.get('code')
    try:
        subprocess.Popen(["adb", "-s", dev_id, "shell", "input", "keyevent", str(code)])
    except: pass
    return "OK"

@app.route('/unlock/<dev_id>')
def unlock(dev_id):
    subprocess.Popen(["adb", "-s", dev_id, "shell", "input", "keyevent", "224"])
    subprocess.Popen(["adb", "-s", dev_id, "shell", "wm", "dismiss-keyguard"])
    subprocess.Popen(["adb", "-s", dev_id, "shell", "input", "swipe", "500", "1500", "500", "200", "300"])
    return "OK"

@app.route('/sleep/<dev_id>')
def sleep(dev_id):
    subprocess.Popen(["adb", "-s", dev_id, "shell", "input", "keyevent", "223"])
    return "OK"

@app.route('/reboot/<dev_id>')
def reboot(dev_id):
    subprocess.Popen(["adb", "-s", dev_id, "reboot"])
    return "OK"

def gen_frames(dev_id):
    try:
        while True:
            try:
                cmd = ["adb", "-s", dev_id, "exec-out", "screencap", "-p"]
                frame = subprocess.check_output(cmd, timeout=5)
                yield (b'--frame\r\n'
                       b'Content-Type: image/png\r\n\r\n' + frame + b'\r\n')
                time.sleep(REFRESH_INTERVAL)
            except:
                time.sleep(1)
    except GeneratorExit:
        pass

@app.route('/stream/<dev_id>')
def stream(dev_id):
    return Response(gen_frames(dev_id), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=PORT, threaded=True)

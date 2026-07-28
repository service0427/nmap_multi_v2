#!/usr/bin/env python3
import os
import sys
import json
import time
import argparse
import subprocess
import signal
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import threading

# Ensure we import modules from src/lib
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "lib"))

from adb import ADBManager
import manifest
import api_client
from lock_manager import DeviceLock, SubnetLock

API_SERVER = api_client.API_SERVER
SHUTDOWN = False

def load_global_config():
    return manifest.load_global_config()

def get_stale_tasks(stale_timeout):
    """Detects and returns proxy_manager.py processes running longer than stale_timeout seconds."""
    stale_devices = []
    try:
        res = subprocess.run(
            ["ps", "-eo", "pid,etimes,args"],
            capture_output=True, text=True, timeout=5
        )
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                if "proxy_manager.py" in line and "grep" not in line:
                    parts = line.strip().split(None, 2)
                    if len(parts) >= 3:
                        pid = parts[0]
                        etimes = int(parts[1])
                        args = parts[2]
                        
                        match = re.search(r"--device\s+([a-zA-Z0-9_-]+)", args)
                        if match and etimes > stale_timeout:
                            stale_devices.append((pid, match.group(1), etimes))
    except Exception:
        pass
    return stale_devices

def kill_stale_task(pid, device_id, elapsed):
    print(f"[⚠️] [{datetime.now().strftime('%T')}] [{device_id}] DETECTED STALE PROCESS (PID: {pid}, Elapsed: {elapsed}s). Force killing...")
    try:
        subprocess.run(f"pkill -9 -f 'proxy_manager.py.*--device {device_id}'", shell=True)
        subprocess.run(f"pkill -9 -f 'web_monitor.py.*{device_id}'", shell=True)
        subprocess.run(f"pkill -9 -f 'gps_simulator.py.*{device_id}'", shell=True)
    except:
        pass
    
    lock_file = f"/home/tech/nmap_multi_v2/logs/devices/{device_id}/tmp/nmap_lock"
    task_json = f"/home/tech/nmap_multi_v2/logs/devices/{device_id}/current_task.json"
    for f in [lock_file, task_json]:
        try:
            os.remove(f)
        except:
            pass
            
    try:
        url = f"http://{API_SERVER}/api/v1/report_result"
        payload = {
            "task_id": "stale_kill",
            "device_id": device_id,
            "status": "FAIL",
            "message": f"STALE_PROCESS_KILLED_ELAPSED_{elapsed}s"
        }
        subprocess.run(
            ["curl", "-s", "-X", "POST", url, "-H", "Content-Type: application/json", "-d", json.dumps(payload)],
            timeout=5
        )
    except:
        pass

# Thread safety lock for exclude dict
exclude_lock = threading.Lock()
exclude_until = {}

def process_device(dev_id, mode, config):
    """Worker function to process a single device in parallel."""
    if SHUTDOWN:
        return

    if manifest.is_device_excluded(dev_id):
        return

    # Check non-blocking device lock
    dev_lock = DeviceLock(dev_id)
    if not dev_lock.acquire():
        # Device is already running a proxy_manager task
        return
    dev_lock.release()

    current_time = int(time.time())

    # Check IP Failure Cooldown (180s)
    ip_fail_gate = f"/home/tech/nmap_multi_v2/logs/devices/{dev_id}/tmp/ip_failed_gate"
    if os.path.exists(ip_fail_gate):
        with exclude_lock:
            exclude_until[dev_id] = current_time + 180
        try:
            os.remove(ip_fail_gate)
        except: pass
        print(f"[IP_BLOCKED] [{dev_id}] IP lookup failed. Applying 180s cooldown.")
        
        task_json = f"/home/tech/nmap_multi_v2/logs/devices/{dev_id}/current_task.json"
        os.makedirs(os.path.dirname(task_json), exist_ok=True)
        with open(task_json, "w") as f:
            json.dump({"status": "IP_COOLDOWN", "exclude_until": current_time + 180}, f)
        return

    # Check if device is in penalty/cooldown
    with exclude_lock:
        until = exclude_until.get(dev_id, 0)
    if current_time < until:
        return

    # Check ON_HOLD state in current_task.json
    task_json = f"/home/tech/nmap_multi_v2/logs/devices/{dev_id}/current_task.json"
    if os.path.exists(task_json):
        try:
            with open(task_json, "r") as f:
                task_data = json.load(f)
                if task_data.get("status") == "ON_HOLD":
                    return
        except:
            pass

    # Post-cleanup & setup
    ADBManager.run_adb(dev_id, "shell \"am force-stop com.nhn.android.nmap; settings put global http_proxy :0\"", timeout=5)
    
    ime_status, _, _ = ADBManager.run_adb(dev_id, "shell settings get secure default_input_method", timeout=5)
    if "com.android.adbkeyboard/.AdbIME" not in ime_status:
        print(f"[*] [{dev_id}] Setting ADBKeyboard default input...")
        ADBManager.run_adb(dev_id, "shell ime enable com.android.adbkeyboard/.AdbIME", timeout=5)
        ADBManager.run_adb(dev_id, "shell ime set com.android.adbkeyboard/.AdbIME", timeout=5)
        
    ADBManager.check_and_fix_zflip(dev_id)
    
    bind_ip = None
    modem_idx = "0"
    if mode == "eth":
        bind_ip = ADBManager.get_bind_ip(dev_id, mode="eth")
        if not bind_ip:
            print(f"[⚠️] [{dev_id}] SKIPPED: Serial Number has no assigned LTE IP.")
            return
        m = re.search(r"\.([0-9]+)\.[0-9]+$", bind_ip)
        if m:
            modem_idx = m.group(1)
    
    sub_lock = None
    if mode == "eth" and config.get("USE_SUBNET_LOCK", True):
        sub_lock = SubnetLock(modem_idx)
        if not sub_lock.acquire():
            return

    os.makedirs(os.path.dirname(task_json), exist_ok=True)
    with open(task_json, "w") as f:
        json.dump({"status": "LAUNCHING"}, f)
        
    response = api_client.request_task(dev_id)
    if response.get("status") == "ERROR":
        with open(task_json, "w") as f:
            json.dump({"status": "IDLE"}, f)
        if sub_lock:
            sub_lock.release()
        return
        
    status_api = response.get("status")
    if status_api != "ok":
        msg = response.get("msg", "")
        if msg == "COOLDOWN_ACTIVE":
            print(f"[COOLDOWN] [{dev_id}] Cooldown active.")
            with exclude_lock:
                exclude_until[dev_id] = current_time + 60
        elif msg == "PENALTY_ACTIVE":
            print(f"[🚨] [{dev_id}] Penalty active (60+ fails).")
            with exclude_lock:
                exclude_until[dev_id] = current_time + 600
        elif msg == "UNAUTHORIZED_DEVICE":
            print(f"[⚠️] [{dev_id}] Unauthorized device.")
            with exclude_lock:
                exclude_until[dev_id] = current_time + 300
        
        with exclude_lock:
            ex_val = exclude_until.get(dev_id, 0)
        with open(task_json, "w") as f:
            json.dump({"status": msg, "exclude_until": ex_val}, f)
            
        if sub_lock:
            sub_lock.release()
        return
        
    task_id = response.get("task_id")
    dest_name = response.get("destination", {}).get("target_name")
    
    print(f"[🚀] [{dev_id}] ALLOCATED: {dest_name} (Task:{task_id}) -> Modem lte{modem_idx} ({bind_ip})")
    
    subprocess.Popen([
        "python3", "/home/tech/nmap_multi_v2/src/core/proxy_manager.py",
        "--device", dev_id,
        "--mode", mode,
        "--task-data", json.dumps(response)
    ])
    
    if sub_lock:
        time.sleep(config.get("STAGGER_DELAY_SEC", 3))
        sub_lock.release()

def signal_handler(signum, frame):
    global SHUTDOWN
    print("\n[!] Shutdown signal received. Stopping async scheduler...")
    SHUTDOWN = True

def main():
    parser = argparse.ArgumentParser(description="Nmap Multi V2 Parallel Async Worker Scheduler")
    parser.add_argument("--mode", required=True, choices=["eth", "local", "wifi"])
    parser.add_argument("--workers", type=int, default=64, help="Max parallel worker threads")
    args = parser.parse_args()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print(f"============================================================")
    print(f"🚀 Nmap Multi V2 Async Scheduler Starting in '{args.mode.upper()}' Mode ({args.workers} Parallel Workers)")
    print(f"============================================================")
    
    try:
        subprocess.run("pkill -9 -f 'proxy_manager.py'", shell=True)
        subprocess.run("pkill -9 -f 'mitmdump'", shell=True)
    except:
        pass

    logs_dir = "/home/tech/nmap_multi_v2/logs"
    if os.path.exists(logs_dir):
        for root, _, files in os.walk(logs_dir):
            for f in files:
                if f == "current_task.json":
                    try:
                        os.remove(os.path.join(root, f))
                    except: pass

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        while not SHUTDOWN:
            try:
                config = load_global_config()
                
                # Clean stale processes
                stale_tasks = get_stale_tasks(config.get("STALE_TASK_TIMEOUT", 600))
                for pid, dev_id, elapsed in stale_tasks:
                    kill_stale_task(pid, dev_id, elapsed)
                    
                devices = ADBManager.get_connected_devices()
                if not devices:
                    print(f"[{datetime.now().strftime('%T')}] No devices connected. Waiting...")
                    time.sleep(5)
                    continue

                # Process all connected devices concurrently across the worker pool
                futures = [executor.submit(process_device, dev_id, args.mode, config) for dev_id in devices]
                for fut in futures:
                    try:
                        fut.result()
                    except Exception as e:
                        pass
                
                time.sleep(2)
            except Exception as e:
                print(f"[ERROR] Scheduler loop exception: {e}")
                time.sleep(5)

if __name__ == "__main__":
    main()

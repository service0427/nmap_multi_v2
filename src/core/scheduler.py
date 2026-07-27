#!/usr/bin/env python3
import os
import sys
import json
import time
import argparse
import subprocess
import fcntl
from datetime import datetime

# Ensure we import ADBManager from src/lib
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "lib"))
from adb import ADBManager
import manifest
import api_client
from lock_manager import DeviceLock, SubnetLock

API_SERVER = api_client.API_SERVER

def load_global_config():
    return manifest.load_global_config()

def get_stale_tasks(stale_timeout):
    """Detects and returns proxy_manager.py processes running longer than stale_timeout seconds."""
    stale_devices = []
    try:
        # Find active Python proxy_manager.py tasks
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
                        
                        # Extract device_id (after --device flag)
                        match = re.search(r"--device\s+([a-zA-Z0-9_-]+)", args)
                        if match and etimes > stale_timeout:
                            stale_devices.append((pid, match.group(1), etimes))
    except Exception:
        pass
    return stale_devices

def kill_stale_task(pid, device_id, elapsed):
    print(f"[⚠️] [{datetime.now().strftime('%T')}] [{device_id}] DETECTED STALE PROCESS (PID: {pid}, Elapsed: {elapsed}s). Force killing...")
    # Kill the sub processes
    try:
        subprocess.run(f"pkill -9 -f 'proxy_manager.py.*--device {device_id}'", shell=True)
        subprocess.run(f"pkill -9 -f 'web_monitor.py.*{device_id}'", shell=True)
        subprocess.run(f"pkill -9 -f 'gps_simulator.py.*{device_id}'", shell=True)
    except:
        pass
    
    # Remove active locks
    lock_file = f"/home/tech/nmap_multi_v2/logs/devices/{device_id}/tmp/nmap_lock"
    task_json = f"/home/tech/nmap_multi_v2/logs/devices/{device_id}/current_task.json"
    for f in [lock_file, task_json]:
        try:
            os.remove(f)
        except:
            pass
            
    # Send fail result to API
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

import re

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=["eth", "local", "wifi"])
    args = parser.parse_args()
    
    print(f"============================================================")
    print(f"🚀 Nmap Multi V2 Scheduler Starting in '{args.mode.upper()}' Mode")
    print(f"============================================================")
    
    # Perform startup cleanups
    try:
        subprocess.run("pkill -9 -f 'proxy_manager.py'", shell=True)
        subprocess.run("pkill -9 -f 'mitmdump'", shell=True)
    except:
        pass

    # Wipe stale current_task locks
    logs_dir = "/home/tech/nmap_multi_v2/logs"
    if os.path.exists(logs_dir):
        for root, _, files in os.walk(logs_dir):
            for f in files:
                if f == "current_task.json":
                    try:
                        os.remove(os.path.join(root, f))
                    except: pass

    exclude_until = {}
    
    while True:
        config = load_global_config()
        
        # 1. Clean stale processes
        stale_tasks = get_stale_tasks(config["STALE_TASK_TIMEOUT"])
        for pid, dev_id, elapsed in stale_tasks:
            kill_stale_task(pid, dev_id, elapsed)
            
        # 2. Retrieve connected devices
        devices = ADBManager.get_connected_devices()
        if not devices:
            print(f"[{datetime.now().strftime('%T')}] No devices connected. Waiting...")
            time.sleep(10)
            continue
            
        current_time = int(time.time())
        print(f"[{datetime.now().strftime('%T')}] Scanning {len(devices)} connected devices...")

        for dev_id in devices:
            if manifest.is_device_excluded(dev_id):
                continue
                
            # Skip if active process already running for device
            dev_lock = DeviceLock(dev_id)
            if not dev_lock.acquire():
                continue
            dev_lock.release()
                
            # Check IP Failure Cooldown (180s)
            ip_fail_gate = f"/home/tech/nmap_multi_v2/logs/devices/{dev_id}/tmp/ip_failed_gate"
            if os.path.exists(ip_fail_gate):
                exclude_until[dev_id] = current_time + 180
                try:
                    os.remove(ip_fail_gate)
                except: pass
                print(f"[IP_BLOCKED] [{dev_id}] IP lookup failed. Applying 180s cooldown.")
                
                # Write to current_task.json
                task_json = f"/home/tech/nmap_multi_v2/logs/devices/{dev_id}/current_task.json"
                os.makedirs(os.path.dirname(task_json), exist_ok=True)
                with open(task_json, "w") as f:
                    json.dump({"status": "IP_COOLDOWN", "exclude_until": exclude_until[dev_id]}, f)
                continue

            # Check if device is in penalty or cooldown
            if dev_id in exclude_until and current_time < exclude_until[dev_id]:
                continue
                
            # Post-cleanup: force stop Naver Map app if lock is absent
            ADBManager.run_adb(dev_id, "shell \"am force-stop com.nhn.android.nmap; settings put global http_proxy :0\"", timeout=5)
            
            # Ensure ADBKeyboard is default input method
            ime_status, _, _ = ADBManager.run_adb(dev_id, "shell settings get secure default_input_method", timeout=5)
            if "com.android.adbkeyboard/.AdbIME" not in ime_status:
                print(f"[*] [{dev_id}] Setting ADBKeyboard default input...")
                ADBManager.run_adb(dev_id, "shell ime enable com.android.adbkeyboard/.AdbIME", timeout=5)
                ADBManager.run_adb(dev_id, "shell ime set com.android.adbkeyboard/.AdbIME", timeout=5)
                
            # Check and override Z Flip state
            ADBManager.check_and_fix_zflip(dev_id)
            
            # Get IP and Modem Subnet index for eth mode
            bind_ip = None
            modem_idx = "0"
            if args.mode == "eth":
                bind_ip = ADBManager.get_bind_ip(dev_id, mode="eth")
                if not bind_ip:
                    print(f"[⚠️] [{dev_id}] SKIPPED: Serial Number has no assigned LTE IP.")
                    continue
                # Extract subnet index (e.g. 192.168.11.121 -> 11)
                m = re.search(r"\.([0-9]+)\.[0-9]+$", bind_ip)
                if m:
                    modem_idx = m.group(1)
            
            # Stagger Subnet lock if enabled (eth mode only)
            sub_lock = None
            if args.mode == "eth" and config["USE_SUBNET_LOCK"]:
                sub_lock = SubnetLock(modem_idx)
                if not sub_lock.acquire():
                    continue

            # Mark as LAUNCHING in current_task.json immediately
            task_json = f"/home/tech/nmap_multi_v2/logs/devices/{dev_id}/current_task.json"
            os.makedirs(os.path.dirname(task_json), exist_ok=True)
            with open(task_json, "w") as f:
                json.dump({"status": "LAUNCHING"}, f)
                
            # Request task from API server
            response = api_client.request_task(dev_id)
            if response.get("status") == "ERROR":
                with open(task_json, "w") as f:
                    json.dump({"status": "IDLE"}, f)
                if sub_lock:
                    sub_lock.release()
                continue
                
            # Analyze API response status
            status_api = response.get("status")
            if status_api != "ok":
                msg = response.get("msg", "")
                if msg == "COOLDOWN_ACTIVE":
                    print(f"[COOLDOWN] [{dev_id}] Cooldown active.")
                    exclude_until[dev_id] = current_time + 60
                elif msg == "PENALTY_ACTIVE":
                    print(f"[🚨] [{dev_id}] Penalty active (60+ fails).")
                    exclude_until[dev_id] = current_time + 600
                elif msg == "UNAUTHORIZED_DEVICE":
                    print(f"[⚠️] [{dev_id}] Unauthorized device.")
                    exclude_until[dev_id] = current_time + 300
                
                with open(task_json, "w") as f:
                    json.dump({"status": msg, "exclude_until": exclude_until.get(dev_id, 0)}, f)
                    
                if sub_lock:
                    sub_lock.release()
                continue
                
            # Spawn proxy_manager.py task in the background
            task_id = response.get("task_id")
            dest_name = response.get("destination", {}).get("target_name")
            dest_id = response.get("destination", {}).get("id")
            device_seq = response.get("device_seq")
            
            print(f"[🚀] [{dev_id}] ALLOCATED: {dest_name} (Task:{task_id}) -> Modem lte{modem_idx} ({bind_ip})")
            
            # Spawn background execution
            subprocess.Popen([
                "python3", "/home/tech/nmap_multi_v2/src/core/proxy_manager.py",
                "--device", dev_id,
                "--mode", args.mode,
                "--task-data", json.dumps(response)
            ])
            
            # Close lock handle in scheduler loop (sub-process keeps running)
            if sub_lock:
                # Keep subnet locked for 5 seconds to stagger launches
                time.sleep(5)
                sub_lock.release()
                
            # Delay before starting next device to prevent CPU spikes
            time.sleep(config["STAGGER_DELAY_SEC"])
            
        time.sleep(10)

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# Nmap Multi V2: Traffic Health Monitor & Auto-Healing Pipeline
# Monitors packet activity for all connected devices every 2 minutes.
# Terminates with SUCCESS when all connected devices have traffic within the last 2 minutes.
# Maximum run time: 2 hours (7200s).

import sys
import os
import time
import glob
import json
import subprocess
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src", "lib"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src", "core"))

from adb import ADBManager
import manifest

MAX_RUNTIME_SEC = 7200  # 2 hours
CHECK_INTERVAL_SEC = 120  # 2 minutes
STALE_TRAFFIC_THRESHOLD_SEC = 180  # 3 minutes

def get_latest_packet_mtime(device_id):
    """Finds the mtime of the most recent packet/event file for a given device."""
    today = datetime.now().strftime("%Y%m%d")
    device_dir = os.path.join(PROJECT_ROOT, "logs", "macro_car", today, device_id)
    
    if not os.path.exists(device_dir):
        return 0

    session_dirs = [os.path.join(device_dir, d) for d in os.listdir(device_dir) if os.path.isdir(os.path.join(device_dir, d))]
    if not session_dirs:
        return 0

    latest_session = max(session_dirs, key=os.path.getmtime)
    
    # Check json packets, events.log, mitm.log
    files = glob.glob(os.path.join(latest_session, "*.json")) + [
        os.path.join(latest_session, "events.log"),
        os.path.join(latest_session, "mitm.log")
    ]
    
    mtimes = [os.path.getmtime(f) for f in files if os.path.exists(f)]
    return max(mtimes) if mtimes else 0

def heal_device(device_id):
    """Diagnoses and heals packet delivery issues for a stagnant device."""
    print(f"  [🛠️ HEAL] [{device_id}] Initiating auto-healing diagnosis...")
    
    # 1. Clear stale locks and task JSON
    task_json = os.path.join(PROJECT_ROOT, "logs", "devices", device_id, "current_task.json")
    lock_file = os.path.join(PROJECT_ROOT, "logs", "devices", device_id, "tmp", "nmap_lock")
    for f in [task_json, lock_file]:
        if os.path.exists(f):
            try:
                os.remove(f)
                print(f"    - Cleared stale lock: {os.path.basename(f)}")
            except: pass

    # 2. Check Frida server on device
    frida_pid, _, _ = ADBManager.run_adb(device_id, "shell pidof frida-server")
    if not frida_pid.strip():
        ADBManager.run_adb(device_id, "shell su -c '/system/bin/frida-server &'")
        print(f"    - Restarted frida-server on device")

    # 3. Check ADB reverse and http_proxy
    seq = None
    try:
        ordered = manifest.get_ordered_devices(include_offline=True)
        if device_id in ordered:
            seq = ordered.index(device_id) + 1
    except: pass
    
    if seq:
        mitm_port = 20000 + seq
        rev_out, _, _ = ADBManager.run_adb(device_id, "reverse --list")
        if str(mitm_port) not in rev_out:
            ADBManager.run_adb(device_id, f"reverse tcp:{mitm_port} tcp:{mitm_port}")
            print(f"    - Re-established ADB reverse tunnel on port {mitm_port}")
            
    # 4. Force-stop Naver Map to let scheduler restart it cleanly
    ADBManager.run_adb(device_id, "shell am force-stop com.nhn.android.nmap")
    print(f"    - Force-stopped Naver Map to trigger clean scheduler launch")

def monitor_cycle():
    """Runs a single 2-minute cycle audit across all connected devices."""
    devices = ADBManager.get_connected_devices()
    if not devices:
        print("[-] No connected ADB devices found.")
        return False

    now = time.time()
    print(f"\n============================================================")
    print(f"📊 Traffic Audit Cycle [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ({len(devices)} devices)")
    print(f"============================================================")

    all_fresh = True
    stale_count = 0
    fresh_count = 0

    for dev in sorted(devices):
        last_mtime = get_latest_packet_mtime(dev)
        elapsed = now - last_mtime if last_mtime > 0 else 9999

        if elapsed <= CHECK_INTERVAL_SEC:
            fresh_count += 1
            print(f"  [✓] [{dev}]: Fresh Packet (Last: {int(elapsed)}s ago) [PASS]")
        else:
            all_fresh = False
            stale_count += 1
            status_str = f"NO TRAFFIC IN {int(elapsed)}s" if last_mtime > 0 else "NO SESSION LOGS"
            print(f"  [❌] [{dev}]: {status_str} (> 2m) -> HEALING")
            if elapsed >= STALE_TRAFFIC_THRESHOLD_SEC:
                heal_device(dev)

    print(f"------------------------------------------------------------")
    print(f"Summary: {fresh_count} Fresh Devices, {stale_count} Stale/No Traffic Devices")

    if all_fresh:
        print(f"\n============================================================")
        print(f"🎉 SUCCESS: All {len(devices)} connected devices generated packet traffic within the last 2 minutes!")
        print(f"============================================================")
        return True
        
    return False

def main():
    start_time = time.time()
    cycle = 1
    
    print(f"============================================================")
    print(f"🚀 Nmap Multi V2: Traffic Monitor & Auto-Healing Engine")
    print(f"Target: All connected devices must have traffic within 2 minutes.")
    print(f"Cycle: Every 2 minutes | Max Duration: 2 Hours (7200s)")
    print(f"============================================================")

    while True:
        elapsed_total = time.time() - start_time
        if elapsed_total >= MAX_RUNTIME_SEC:
            print(f"\n[⏱️] Reached 2-hour max runtime limit ({int(elapsed_total)}s). Exiting monitor loop.")
            break

        print(f"\n--- [Cycle #{cycle}] (Elapsed: {int(elapsed_total)}s / {MAX_RUNTIME_SEC}s) ---")
        success = monitor_cycle()
        if success:
            sys.exit(0)

        print(f"\n[⏳] Sleeping 120s before next check cycle...")
        time.sleep(CHECK_INTERVAL_SEC)
        cycle += 1

if __name__ == "__main__":
    main()

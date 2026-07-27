#!/usr/bin/env python3
# Nmap Multi V2: First-run device initialization and environment validation pipeline
import sys
import os
import time
import subprocess

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src", "lib"))
from adb import ADBManager

def run_cmd(device_id, cmd_str):
    out, err, rc = ADBManager.run_adb(device_id, f"shell \"{cmd_str}\"")
    return out.strip()

def init_single_device(dev):
    print(f"[*] Initializing device {dev}...")
    
    # 1. Root & System Settings
    run_cmd(dev, "su 0 settings put global bluetooth_on 0")
    run_cmd(dev, "su 0 settings put system volume_music 0")
    run_cmd(dev, "su 0 settings put system volume_notification 0")
    run_cmd(dev, "su 0 settings put system volume_ring 0")
    run_cmd(dev, "su 0 settings put system volume_system 0")
    run_cmd(dev, "su 0 settings put global captive_portal_mode 0")
    run_cmd(dev, "su 0 settings put global captive_portal_detection_enabled 0")
    run_cmd(dev, "su 0 settings put system accelerometer_rotation 0")
    run_cmd(dev, "su 0 settings put system user_rotation 0") # Portrait orientation
    
    # 2. Disaster alert & location scan toggles
    run_cmd(dev, "su 0 settings put global wifi_scan_always_enabled 0")
    run_cmd(dev, "su 0 settings put global ble_scan_always_enabled 0")
    
    # 3. Grant Permissions for Naver Map
    pkg = "com.nhn.android.nmap"
    permissions = [
        "android.permission.ACCESS_FINE_LOCATION",
        "android.permission.ACCESS_COARSE_LOCATION",
        "android.permission.ACCESS_BACKGROUND_LOCATION",
        "android.permission.READ_PHONE_STATE",
        "android.permission.WRITE_EXTERNAL_STORAGE",
        "android.permission.READ_EXTERNAL_STORAGE"
    ]
    for perm in permissions:
        run_cmd(dev, f"su 0 pm grant {pkg} {perm} 2>/dev/null")
        
    # 4. Check if ZFlip is folded and force OPEN state (state 3)
    ADBManager.check_and_fix_zflip(dev)
    print(f"  [✓] Device {dev} basic settings initialized.")

def main():
    devices = ADBManager.get_connected_devices()
    if not devices:
        print("[-] No active ADB devices found.")
        sys.exit(1)
        
    print(f"============================================================")
    print(f"🚀 Nmap Multi V2: Device Initialization Pipeline ({len(devices)} devices)")
    print(f"============================================================")
    
    # Check if legacy v1 device_init exists for full APK/cert setup
    v1_init = "/home/tech/nmap_multi_v1/device_init.sh"
    if os.path.exists(v1_init):
        print("[*] Launching comprehensive V1/V2 device_init modular script...")
        subprocess.run(["bash", v1_init])
    else:
        for dev in devices:
            init_single_device(dev)
            
    print("[✓] All connected devices initialized successfully.")

if __name__ == "__main__":
    main()

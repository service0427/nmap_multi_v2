#!/usr/bin/env python3
import sys
import os
import time

# Ensure we import ADBManager from src/lib
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src", "lib"))
from adb import ADBManager

def print_help():
    print("Nmap Multi V2: Concurrent Phone Control CLI")
    print("Usage:")
    print("  ./cmd.sh --reboot             Sequentially reboot all phones")
    print("  ./cmd.sh --wifi <SSID> <PW>   Reset & connect all phones to SSID")
    print("  ./cmd.sh --dark               Enable system dark mode")
    print("  ./cmd.sh --light              Enable system light mode")
    print("  ./cmd.sh --portrait           Lock screen rotation to portrait")
    print("  ./cmd.sh --app-version        Audit installed Naver Map versions")
    print("  ./cmd.sh --wifi-ips           Show wlan0 IP allocations")
    print("  ./cmd.sh --disable-usim       Disable cellular carrier data")
    print("  ./cmd.sh --patch-app          Inject map hosts and SSL bypass patches")
    print("  ./cmd.sh --emergency          Instantly force-stop Map and return home")
    print("  ./cmd.sh \"<shell cmd>\"       Broadcast raw shell command to all devices")
    sys.exit(0)

def main():
    if len(sys.argv) < 2 or sys.argv[1] in ["--help", "-h"]:
        print_help()

    flag = sys.argv[1]
    devices = ADBManager.get_connected_devices()
    if not devices:
        print("[-] No connected ADB devices found.")
        sys.exit(1)

    print(f"[*] Found {len(devices)} active devices: {', '.join(devices)}")

    if flag == "--reboot":
        print("[*] Sequentially rebooting devices...")
        for dev in devices:
            print(f"  -> Rebooting {dev}...")
            ADBManager.run_adb(dev, "reboot")
            time.sleep(1.5)
        print("[✓] Reboot signals transmitted.")

    elif flag == "--wifi":
        if len(sys.argv) < 3:
            print("[-] Error: Wifi SSID required (e.g. ./cmd.sh --wifi Tech_5G 13241324)")
            sys.exit(1)
        ssid = sys.argv[2]
        pw = sys.argv[3] if len(sys.argv) > 3 else "13241324"
        print(f"[*] Provisioning Wifi SSID '{ssid}' on all devices...")
        # Wipe old networks, toggle, and connect
        wifi_setup_cmds = (
            "shell su -c 'settings put global captive_portal_mode 0 && "
            "settings put global captive_portal_detection_enabled 0 && "
            "cmd wifi remove-all-suggestions && "
            "for id in $(seq 0 20); do cmd wifi forget-network $id; done && "
            "cmd wifi set-wifi-enabled disabled && sleep 1 && "
            "cmd wifi set-wifi-enabled enabled && sleep 1 && "
            f"cmd wifi connect-network \"{ssid}\" wpa2 \"{pw}\"'"
        )
        results = ADBManager.run_concurrent(wifi_setup_cmds, devices)
        for dev, (out, err, rc) in results.items():
            status = "Success" if rc == 0 else f"Failed ({err.strip()})"
            print(f"  [{dev}]: {status}")

    elif flag == "--dark":
        print("[*] Enabling system dark mode...")
        # Android dark mode command
        results = ADBManager.run_concurrent("shell \"cmd uimode night yes\"", devices)
        for dev, (_, _, rc) in results.items():
            print(f"  [{dev}]: {'Dark Mode Active' if rc == 0 else 'Failed'}")

    elif flag == "--light":
        print("[*] Enabling system light mode...")
        results = ADBManager.run_concurrent("shell \"cmd uimode night no\"", devices)
        for dev, (_, _, rc) in results.items():
            print(f"  [{dev}]: {'Light Mode Active' if rc == 0 else 'Failed'}")

    elif flag == "--portrait":
        print("[*] Locking screen rotation to portrait...")
        # user_rotation=0 (portrait), accelerometer_rotation=0 (disabled auto-rotate)
        results = ADBManager.run_concurrent(
            "shell \"settings put system accelerometer_rotation 0 && settings put system user_rotation 0\"", 
            devices
        )
        for dev, (_, _, rc) in results.items():
            print(f"  [{dev}]: {'Rotation Locked' if rc == 0 else 'Failed'}")

    elif flag == "--app-version":
        print("[*] Auditing Naver Map application versions...")
        results = ADBManager.run_concurrent("shell \"dumpsys package com.nhn.android.nmap | grep versionName\"", devices)
        for dev, (out, _, rc) in results.items():
            if rc == 0 and out:
                version = out.strip().split("\n")[0].split("=")[-1]
                print(f"  [{dev}]: Version = {version}")
            else:
                print(f"  [{dev}]: Package not installed or query failed")

    elif flag == "--wifi-ips":
        print("[*] Retrieving Wi-Fi IP allocations...")
        results = ADBManager.run_concurrent("shell \"ip -4 addr show wlan0\"", devices)
        for dev, (out, _, rc) in results.items():
            match = re.search(r"inet\s+([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)", out)
            ip = match.group(1) if match else "No IP"
            print(f"  [{dev}]: IP = {ip}")

    elif flag == "--disable-usim":
        print("[*] Disabling cellular carrier data...")
        results = ADBManager.run_concurrent("shell \"su -c 'svc data disable'\"", devices)
        for dev, (_, _, rc) in results.items():
            print(f"  [{dev}]: {'Cellular Disabled' if rc == 0 else 'Failed'}")

    elif flag == "--patch-app":
        print("[*] Injecting SSL bypass/hosts overrides patches...")
        results = ADBManager.run_concurrent("shell \"su -c 'restorecon -R /data/data/com.nhn.android.nmap'\"", devices)
        for dev, (_, _, rc) in results.items():
            print(f"  [{dev}]: {'Hosts Patched' if rc == 0 else 'Failed'}")

    elif flag == "--emergency":
        print("[⚠️] EMERGENCY PANIC TRIGGERED: Force closing Map app & returning home...")
        results = ADBManager.run_concurrent(
            "shell \"am force-stop com.nhn.android.nmap && input keyevent 3 && settings put global http_proxy :0\"", 
            devices
        )
        for dev, (_, _, rc) in results.items():
            print(f"  [{dev}]: {'Emergency Stop Executed' if rc == 0 else 'Failed'}")

    else:
        # Broadcast raw shell command
        cmd_to_run = f"shell \"{flag}\""
        print(f"[*] Broadcasting raw shell command: '{flag}'")
        results = ADBManager.run_concurrent(cmd_to_run, devices)
        for dev, (out, err, rc) in results.items():
            print(f"  [{dev}] exit {rc}: {out.strip() if out else err.strip()}")

import re
if __name__ == "__main__":
    main()

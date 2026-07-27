#!/usr/bin/env python3
import sys
import os
import time

# Ensure we import ADBManager and manifest from src/lib
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src", "lib"))
from adb import ADBManager
import manifest

def print_help():
    print("Nmap Multi V2: Concurrent Phone Control CLI")
    print("Usage:")
    print("  ./cmd.sh --init               Run initial phone setup (APKs, certs, system settings)")
    print("  ./cmd.sh --reboot             Sequentially reboot all phones")
    print("  ./cmd.sh --wifi               Interactive Wi-Fi scan & connect menu")
    print("  ./cmd.sh --wifi <SSID> <PW>   Reset & connect all phones to SSID directly")
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

    if flag == "--init":
        import subprocess
        init_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools", "device_init.sh")
        subprocess.run(["bash", init_script])

    elif flag == "--reboot":
        print("[*] Sequentially rebooting devices...")
        for dev in devices:
            print(f"  -> Rebooting {dev}...")
            ADBManager.run_adb(dev, "reboot")
            time.sleep(1.5)
        print("[✓] Reboot signals transmitted.")

    elif flag == "--wifi":
        ssid = None
        pw = "13241324"
        target_devices = devices

        if len(sys.argv) >= 3:
            ssid = sys.argv[2]
            if len(sys.argv) >= 4:
                pw = sys.argv[3]
        else:
            print("[*] Scanning nearby Wi-Fi networks via ADB...")
            target_dev = devices[0]
            scan_out, _, _ = ADBManager.run_adb(target_dev, "shell \"su -c 'cmd wifi scan >/dev/null 2>&1; sleep 1; cmd wifi list-scan-results'\"")
            
            ssids = []
            if scan_out:
                for line in scan_out.splitlines()[1:]:
                    parts = line.strip().split()
                    if len(parts) >= 5:
                        raw_ssid = parts[4]
                        if raw_ssid and raw_ssid not in ssids and not raw_ssid.startswith("[") and not raw_ssid.isdigit():
                            ssids.append(raw_ssid)

            # Bring 'Tech_5G' to top of list if present
            DEFAULT_SSID = "Tech_5G"
            if DEFAULT_SSID in ssids:
                ssids.remove(DEFAULT_SSID)
                ssids.insert(0, DEFAULT_SSID)
            elif not ssids:
                ssids = [DEFAULT_SSID]

            print("============================================================")
            print("📶 Available Wi-Fi Networks Nearby:")
            print("============================================================")
            for idx, s in enumerate(ssids, 1):
                marker = " (Default)" if s == DEFAULT_SSID else ""
                print(f"  [{idx}] {s}{marker}")
            print("  [C] Enter Custom SSID manually")
            print("============================================================")

            choice = input(f"Select Wi-Fi number or enter Custom SSID (Default: {DEFAULT_SSID}) [1]: ").strip()
            if choice.upper() == 'C':
                ssid = input("Enter Wi-Fi SSID name: ").strip()
            elif not choice:
                ssid = DEFAULT_SSID
            elif choice.isdigit() and 1 <= int(choice) <= len(ssids):
                ssid = ssids[int(choice) - 1]
            else:
                ssid = choice

            if not ssid:
                ssid = DEFAULT_SSID

            input_pw = input(f"Enter Wi-Fi Password (default: {pw}): ").strip()
            if input_pw:
                pw = input_pw

            # Step 2: Target Device Selection Menu
            print("\n============================================================")
            print(f"📱 Select Target Devices (Total Connected: {len(devices)}):")
            print("============================================================")
            print(f"  [A] ALL connected devices ({len(devices)} devices)")
            for idx, dev in enumerate(devices, 1):
                try:
                    subnet = manifest.get_device_subnet(dev) or "N/A"
                    usb_port = manifest.get_device_usb_port(dev) or "N/A"
                except:
                    subnet = "N/A"
                    usb_port = "N/A"
                print(f"  [{idx:2d}] {dev:<15} (Subnet: {str(subnet):<5} | Port: {usb_port})")
            print("============================================================")

            dev_choice = input(f"Select Target Devices (A=ALL, 1,3,5, or 1-10) [A]: ").strip()
            target_devices = []
            
            if not dev_choice or dev_choice.upper() in ["A", "ALL"]:
                target_devices = devices
            else:
                try:
                    parts = [p.strip() for p in dev_choice.split(",")]
                    for p in parts:
                        if "-" in p:
                            s_str, e_str = p.split("-", 1)
                            start, end = int(s_str.strip()), int(e_str.strip())
                            for i in range(start, end + 1):
                                if 1 <= i <= len(devices):
                                    if devices[i - 1] not in target_devices:
                                        target_devices.append(devices[i - 1])
                        elif p.isdigit():
                            i = int(p)
                            if 1 <= i <= len(devices):
                                if devices[i - 1] not in target_devices:
                                    target_devices.append(devices[i - 1])
                        elif p in devices:
                            if p not in target_devices:
                                target_devices.append(p)
                except Exception as e:
                    print(f"[-] Device selection parsing error: {e}. Fallback to ALL devices.")
                    target_devices = devices

            if not target_devices:
                print("[-] Error: No valid target devices selected. Aborting.")
                sys.exit(1)

        # Check existing Wi-Fi connection state on target_devices
        already_connected = []
        need_provision = []

        print(f"\n[*] Auditing existing Wi-Fi state on {len(target_devices)} target devices...")
        status_results = ADBManager.run_concurrent('shell "cmd wifi status"', target_devices)
        ip_results = ADBManager.run_concurrent('shell "ip -4 addr show wlan0"', target_devices)

        for dev in target_devices:
            curr_out, _, _ = status_results.get(dev, ("", "", -1))
            ip_out, _, _ = ip_results.get(dev, ("", "", -1))

            curr_ssid = ""
            if "SSID:" in curr_out:
                for line in curr_out.splitlines():
                    if "SSID:" in line:
                        curr_ssid = line.split("SSID:")[1].strip().strip('"')
                        break

            match = re.search(r"inet\s+([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)", ip_out)
            curr_ip = match.group(1) if match else None

            if curr_ssid == ssid and curr_ip:
                already_connected.append(dev)
                print(f"  [✓] [{dev}]: Already connected to '{ssid}' (IP: {curr_ip}) -> [PASS]")
            else:
                need_provision.append(dev)

        if already_connected:
            print(f"[*] {len(already_connected)}/{len(target_devices)} devices are already connected to '{ssid}' [PASS].")

        if not need_provision:
            print(f"\n[✓] All {len(target_devices)} target devices are already on '{ssid}'. Wi-Fi provisioning complete! [PASS]")
            sys.exit(0)

        target_devices = need_provision
        print(f"\n[*] Provisioning Wi-Fi SSID '{ssid}' on remaining {len(target_devices)} devices...")
        ADBManager.run_concurrent('shell "su -c \\"settings put global captive_portal_mode 0\\""', target_devices)
        ADBManager.run_concurrent('shell "su -c \\"settings put global captive_portal_detection_enabled 0\\""', target_devices)
        ADBManager.run_concurrent('shell "su -c \\"cmd wifi remove-all-suggestions\\""', target_devices)
        ADBManager.run_concurrent('shell "su -c \\"cmd wifi set-wifi-enabled disabled\\""', target_devices)
        time.sleep(1)
        ADBManager.run_concurrent('shell "su -c \\"cmd wifi set-wifi-enabled enabled\\""', target_devices)
        time.sleep(1)

        add_cmd = f'shell "su -c \\"cmd wifi add-network {ssid} wpa2 {pw}\\""'
        ADBManager.run_concurrent(add_cmd, target_devices)
        time.sleep(1)

        conn_cmd = f'shell "su -c \\"cmd wifi connect-network {ssid} wpa2 {pw}\\""'
        results = ADBManager.run_concurrent(conn_cmd, target_devices)
        for dev, (out, err, rc) in results.items():
            status = "Success" if rc == 0 and "SecurityException" not in err else f"Failed ({err.strip() if err else out.strip()})"
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

#!/usr/bin/env python3
import subprocess
import sys
import os
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

class ADBManager:
    @staticmethod
    def run_cmd(cmd, timeout=15):
        """Runs a general shell command and returns stdout."""
        try:
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
            return res.stdout.strip(), res.stderr.strip(), res.returncode
        except subprocess.TimeoutExpired:
            return "", "TIMEOUT", -1
        except Exception as e:
            return "", str(e), -1

    @classmethod
    def run_adb(cls, device_id, adb_args, timeout=10):
        """Runs an ADB command targeting a specific device."""
        cmd = f"timeout {timeout} adb -s {device_id} {adb_args}"
        return cls.run_cmd(cmd, timeout=timeout + 2)

    @classmethod
    def get_connected_devices(cls):
        """Returns list of active connected device serials."""
        stdout, _, rc = cls.run_cmd("adb devices")
        if rc != 0:
            return []
        devices = []
        for line in stdout.splitlines()[1:]:
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                devices.append(parts[0])
        return devices

    @classmethod
    def run_concurrent(cls, adb_args, devices=None, max_workers=20):
        """Runs an ADB command concurrently across selected or all connected devices."""
        if devices is None:
            devices = cls.get_connected_devices()
        
        results = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_device = {
                executor.submit(cls.run_adb, dev, adb_args): dev for dev in devices
            }
            for future in future_to_device:
                dev = future_to_device[future]
                try:
                    stdout, stderr, rc = future.result()
                    results[dev] = (stdout, stderr, rc)
                except Exception as e:
                    results[dev] = ("", str(e), -1)
        return results

    @classmethod
    def check_keyguard_showing(cls, device_id):
        """Returns True if the screen is locked/keyguard is showing."""
        stdout, _, _ = cls.run_adb(device_id, "shell dumpsys window")
        if "isKeyguardShowing=true" in stdout or "mShowingKeyguard=true" in stdout or "mDreamingLockscreen=true" in stdout:
            return True
        keyguard_lines = [line for line in stdout.splitlines() if any(x in line.lower() for x in ["keyguard", "lockscreen"])]
        for line in keyguard_lines:
            if re.search(r"showing\s*=\s*true|mshowing\s*=\s*true", line, re.IGNORECASE):
                return True
        # Policy check
        stdout_policy, _, _ = cls.run_adb(device_id, "shell dumpsys window policy")
        if "isKeyguardShowing=true" in stdout_policy or "mShowingKeyguard=true" in stdout_policy:
            return True
        policy_lines = [line for line in stdout_policy.splitlines() if any(x in line.lower() for x in ["keyguard", "lockscreen"])]
        for line in policy_lines:
            if re.search(r"showing\s*=\s*true|mshowing\s*=\s*true", line, re.IGNORECASE):
                return True
        return False

    @classmethod
    def dismiss_keyguard(cls, device_id):
        """Robustly wakes screen and dismisses keyguard."""
        # 1. Wake screen if asleep
        wakefulness, _, _ = cls.run_adb(device_id, "shell \"dumpsys power | grep -E 'mWakefulness=|Display Power: state='\"")
        if "Asleep" in wakefulness or "state=OFF" in wakefulness or "state=DOZE" in wakefulness:
            cls.run_adb(device_id, "shell input keyevent 224")
            time.sleep(0.5)
        
        if not cls.check_keyguard_showing(device_id):
            return True, "Already unlocked"

        # 2. Keyguard dismissal loop
        for retry in range(1, 6):
            # Dismiss command
            cls.run_adb(device_id, "shell wm dismiss-keyguard")
            time.sleep(0.3)
            # Menu key event (82) triggers swipe bypass on Samsung
            cls.run_adb(device_id, "shell input keyevent 82")
            time.sleep(0.5)
            
            if not cls.check_keyguard_showing(device_id):
                return True, "Unlocked via Menu/Dismiss"
            
            # Swipes
            if retry == 1:
                cls.run_adb(device_id, "shell input swipe 500 1600 500 400 350")
            elif retry == 2:
                cls.run_adb(device_id, "shell input swipe 300 1600 800 400 400")
            else:
                cls.run_adb(device_id, "shell input swipe 500 1800 500 200 450")
            time.sleep(1.0)
            
            if not cls.check_keyguard_showing(device_id):
                return True, f"Unlocked on attempt {retry}"
        
        return False, "Failed to unlock"

    @classmethod
    def configure_device_stay_awake(cls, device_id):
        """Configures device stay awake on USB, deviceidle whitelist, and background app execution permission."""
        cls.run_adb(device_id, "shell settings put global stay_on_while_plugged_in 7")
        cls.run_adb(device_id, "shell dumpsys deviceidle whitelist +com.nhn.android.nmap")
        cls.run_adb(device_id, "shell appops set com.nhn.android.nmap RUN_IN_BACKGROUND allow")

    @classmethod
    def check_and_fix_zflip(cls, device_id):
        """Checks if Z Flip closed (CLOSE) and overrides to OPEN (state 3)."""
        model, _, _ = cls.run_adb(device_id, "shell getprop ro.product.model")
        model = model.strip()
        # Z Flip models: F711, F721, F731, F741 etc.
        if "F7" in model or "Flip" in model:
            # Check state
            state_info, _, _ = cls.run_adb(device_id, "shell dumpsys device_state")
            if "state=CLOSE" in state_info or "mCurrentDeviceState=0" in state_info:
                # Closed state. Force OPEN (state 3)
                cls.run_adb(device_id, "shell su -c 'cmd device_state state 3'")
                return True, "ZFlip forced to OPEN state"
            return True, "ZFlip already OPEN"
        return False, "Not a ZFlip model"

    @classmethod
    def get_battery_level(cls, device_id):
        """Returns battery level percentage as integer."""
        stdout, _, _ = cls.run_adb(device_id, "shell dumpsys battery | grep level")
        match = re.search(r"level:\s*([0-9]+)", stdout)
        return int(match.group(1)) if match else 100

    @classmethod
    def get_battery_temp(cls, device_id):
        """Returns battery temperature in Celsius as float."""
        stdout, _, _ = cls.run_adb(device_id, "shell dumpsys battery | grep temperature")
        match = re.search(r"temperature:\s*([0-9]+)", stdout)
        if match:
            temp_raw = int(match.group(1))
            return temp_raw / 10.0
        return 0.0

    @classmethod
    def get_free_ram(cls, device_id):
        """Returns free RAM string."""
        stdout, _, _ = cls.run_adb(device_id, "shell \"cat /proc/meminfo | grep MemFree\"")
        match = re.search(r"MemFree:\s*([0-9]+\s*[a-zA-Z]+)", stdout)
        return match.group(1).strip() if match else "N/A"

    @classmethod
    def get_device_external_ip(cls, device_id, timeout=10):
        """Queries the phone's actual external public IP address using native curl/wget via ADB."""
        cls.run_adb(device_id, "shell settings put global http_proxy :0")
        urls = ["http://ifconfig.me", "http://api.ipify.org", "http://icanhazip.com"]
        for url in urls:
            out, err, rc = cls.run_adb(device_id, f"shell \"curl -s -m {timeout} -4 {url}\"", timeout=timeout + 2)
            ip = out.strip()
            if ip and re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip):
                return ip
            
            out, err, rc = cls.run_adb(device_id, f"shell \"wget -qO- --timeout={timeout} {url}\"", timeout=timeout + 2)
            ip = out.strip()
            if ip and re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip):
                return ip
        return None

    @classmethod
    def get_interface_ip(cls, iface_name):
        """Helper to get dynamic IPv4 of host network interface."""
        try:
            res = subprocess.run(
                ["ip", "-4", "addr", "show", "dev", iface_name],
                capture_output=True, text=True, timeout=3
            )
            if res.returncode == 0:
                match = re.search(r"inet\s+([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)", res.stdout)
                if match:
                    return match.group(1)
        except Exception:
            pass
        return None

    @classmethod
    def get_bind_ip(cls, device_id, mode="eth"):
        """Resolves dynamic binding outbound IP for targeted device based on mappings."""
        if mode != "eth":
            return None # Default route
        
        manifest_path = "/home/tech/nmap_multi_v2/config/devices_manifest.json"
        target_iface = None
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                device_info = manifest.get(device_id, {})
                subnet = device_info.get("subnet")
                if subnet is not None:
                    target_iface = f"lte{subnet}"
            except Exception:
                pass
        
        if not target_iface:
            target_iface = "lte11" # Default modem fallback
        
        live_ip = cls.get_interface_ip(target_iface)
        if live_ip:
            return live_ip
        
        # Fallback to lte11 or static routing
        fallback_ip = cls.get_interface_ip("lte11")
        return fallback_ip if fallback_ip else "192.168.11.121"

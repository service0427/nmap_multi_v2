import os
import sys
import json
import time
import subprocess
from datetime import datetime

# Add project lib to sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src", "lib"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "dev_control"))

import config
import manifest
from adb import ADBManager

class DeviceService:
    @staticmethod
    def get_connected_devices():
        return ADBManager.get_connected_devices()

    @staticmethod
    def get_all_device_states():
        devices = DeviceService.get_connected_devices()
        device_states = []

        for dev_id in devices:
            dev_dir = os.path.join(config.DEVICES_DIR, dev_id)
            task_json_path = os.path.join(dev_dir, "current_task.json")

            status = "IDLE"
            task_id = "-"
            dest_name = "-"
            dest_id = "-"
            device_seq = "-"
            real_ip = "-"
            exclude_until = 0
            step = "IDLE_READY"
            last_active = "-"

            if os.path.exists(task_json_path):
                try:
                    mtime = os.path.getmtime(task_json_path)
                    last_active = datetime.fromtimestamp(mtime).strftime("%H:%M:%S")
                    with open(task_json_path, "r") as f:
                        data = json.load(f)
                        status = data.get("status", "IDLE")
                        task_id = data.get("task_id", "-")
                        dest_name = data.get("dest_name") or data.get("destination", {}).get("target_name", "-")
                        dest_id = data.get("dest_id", "-")
                        device_seq = data.get("device_seq", "-")
                        real_ip = data.get("real_ip", "-")
                        exclude_until = data.get("exclude_until", 0)
                except:
                    pass

            # Check if active process running for device
            is_running = DeviceService.is_process_running(dev_id)
            lock_path = os.path.join(dev_dir, "tmp", "nmap_lock")
            if os.path.exists(lock_path):
                is_running = True

            # Resolve detailed state tag
            current_time = int(time.time())
            rem = max(0, exclude_until - current_time)

            if is_running:
                step = status if status not in ["IDLE", "LAUNCHING", "PENALTY_ACTIVE", "IP_COOLDOWN"] else "RUNNING"
            elif status == "IP_COOLDOWN" and rem > 0:
                step = f"IP_COOLDOWN ({rem}s)"
            elif status == "PENALTY_ACTIVE" and rem > 0:
                step = f"PENALTY ({rem}s)"
            elif status == "LAUNCHING":
                step = "LAUNCHING"
            elif status == "ON_HOLD":
                step = "ON_HOLD (PAUSED)"
            else:
                step = "IDLE_READY"

            # Get device subnet accurately using manifest
            subnet = "lte11"
            try:
                subnet = manifest.get_device_subnet(dev_id) or "lte11"
            except:
                pass

            device_states.append({
                "device_id": dev_id,
                "subnet": subnet,
                "real_ip": real_ip,
                "status": status,
                "step": step,
                "is_running": is_running,
                "task_id": task_id,
                "device_seq": device_seq,
                "destination": dest_name,
                "dest_id": dest_id,
                "battery": "100%",
                "last_active": last_active
            })

        return device_states

    @staticmethod
    def is_process_running(device_id):
        try:
            res = subprocess.run(
                f"pgrep -f 'proxy_manager.py.*--device {device_id}'",
                shell=True, capture_output=True, text=True, timeout=2
            )
            if res.returncode == 0 and res.stdout.strip():
                return True
        except:
            pass
        return False

    @staticmethod
    def start_device(device_id):
        """Immediately enables device, clears cooldown, and dispatches task."""
        print(f"[DEV_CONTROL] Immediate START triggered for device: {device_id}")
        DeviceService.clear_cooldown(device_id)
        return True

    @staticmethod
    def pause_device(device_id):
        """Pauses device from receiving new tasks once current session finishes."""
        print(f"[DEV_CONTROL] PAUSE triggered for device: {device_id}")
        dev_dir = os.path.join(config.DEVICES_DIR, device_id)
        os.makedirs(dev_dir, exist_ok=True)
        task_json_path = os.path.join(dev_dir, "current_task.json")
        with open(task_json_path, "w") as f:
            json.dump({"status": "ON_HOLD", "exclude_until": int(time.time()) + 86400}, f)
        return True

    @staticmethod
    def stop_device(device_id, reason="MANUAL_DEV_CONTROL_STOP"):
        """Stops single device without touching other devices."""
        print(f"[DEV_CONTROL] Stopping target device: {device_id} (Reason: {reason})")
        # 1. Kill proxy_manager process for this device
        try:
            subprocess.run(f"pkill -9 -f 'proxy_manager.py.*--device {device_id}'", shell=True)
            subprocess.run(f"pkill -9 -f 'web_monitor.py.*{device_id}'", shell=True)
            subprocess.run(f"pkill -9 -f 'gps_simulator.py.*{device_id}'", shell=True)
            ADBManager.run_adb(device_id, "shell am force-stop com.nhn.android.nmap", timeout=3)
            ADBManager.run_adb(device_id, "shell settings put global http_proxy :0", timeout=3)
        except Exception as e:
            print(f"Error stopping device process: {e}")

        # 2. Clear current_task.json and lock files
        dev_dir = os.path.join(config.DEVICES_DIR, device_id)
        for fname in ["current_task.json", "tmp/nmap_lock", "tmp/ip_failed_gate"]:
            fpath = os.path.join(dev_dir, fname)
            if os.path.exists(fpath):
                try:
                    os.remove(fpath)
                except:
                    pass

        return True

    @staticmethod
    def restart_device(device_id):
        """Restarts a single device gracefully."""
        DeviceService.stop_device(device_id, reason="MANUAL_DEV_RESTART")
        time.sleep(1)
        # Re-enforce audio mute and DND
        DeviceService.mute_device(device_id)
        return True

    @staticmethod
    def mute_device(device_id):
        """Forces 6 audio streams to 0 and sets DND (zen_mode 2)."""
        try:
            for s in range(6):
                ADBManager.run_adb(device_id, f"shell media volume --stream {s} --set 0", timeout=2)
            ADBManager.run_adb(device_id, "shell settings put system mode_ringer 0", timeout=2)
            ADBManager.run_adb(device_id, "shell cmd audio set-ringer-mode 0", timeout=2)
            ADBManager.run_adb(device_id, "shell settings put global zen_mode 2", timeout=2)
            ADBManager.run_adb(device_id, "shell cmd notification set_dnd on", timeout=2)
            return True
        except:
            return False

    @staticmethod
    def clear_cooldown(device_id):
        """Clears IP failure gates and penalty locks for target device."""
        dev_dir = os.path.join(config.DEVICES_DIR, device_id)
        for fname in ["tmp/ip_failed_gate", "current_task.json"]:
            fpath = os.path.join(dev_dir, fname)
            if os.path.exists(fpath):
                try:
                    os.remove(fpath)
                except:
                    pass
        return True

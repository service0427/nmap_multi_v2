#!/usr/bin/env python3
import subprocess
import time
import os
import sys
import json
from datetime import datetime

V2_ROOT = "/home/tech/nmap_multi_v2"
sys.path.insert(0, os.path.join(V2_ROOT, "src", "lib"))
try:
    import manifest
    MANIFEST_AVAILABLE = True
except ImportError:
    MANIFEST_AVAILABLE = False

CHECK_INTERVAL_SEC = 30
ADB_TIMEOUT_SEC = 5
TECH_USER = "tech"

def run_adb_cmd(args, timeout_sec=5):
    cmd = ["timeout", str(timeout_sec), "adb"] + args
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec + 2)
        if res.returncode == 124:
            return False, "", "ADB command timed out"
        return True, res.stdout, res.stderr
    except Exception as e:
        return False, "", f"Execution error: {e}"

def log(level, message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] {message}", flush=True)

def get_adb_processes():
    processes = []
    try:
        res = subprocess.run(["ps", "-Ao", "pid,user,args"], capture_output=True, text=True, check=True)
        for line in res.stdout.strip().split("\n")[1:]:
            parts = line.strip().split(None, 2)
            if len(parts) >= 3:
                pid, user, cmd = parts[0], parts[1], parts[2]
                if "adb" in cmd and "grep" not in cmd and "adb_recovery_monitor" not in cmd:
                    try:
                        processes.append((int(pid), user, cmd))
                    except ValueError: pass
    except Exception as e:
        log("ERROR", f"Failed to list processes: {e}")
    return processes

def kill_processes(pids, use_sudo=False):
    if not pids: return
    log("INFO", f"Killing processes (use_sudo={use_sudo}): {pids}")
    cmd = ["sudo", "kill", "-9"] if use_sudo else ["kill", "-9"]
    cmd.extend(str(pid) for pid in pids)
    try:
        subprocess.run(cmd, check=True)
    except Exception as e:
        log("ERROR", f"Failed to kill processes: {e}")

def restart_frida_servers():
    """Ensure frida-server is running on all attached ADB devices after recovery."""
    log("INFO", "Triggering frida-server auto-restart on attached devices...")
    try:
        success, stdout, _ = run_adb_cmd(["devices"], timeout_sec=5)
        if success:
            for line in stdout.strip().split("\n")[1:]:
                if "device" in line and not line.startswith("*"):
                    dev = line.split()[0]
                    try:
                        subprocess.run(["adb", "-s", dev, "shell", "su -c pkill -9 frida-server"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
                        subprocess.run(["adb", "-s", dev, "shell", "su -c /system/bin/frida-server &"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
                    except: pass
            log("SUCCESS", "frida-server auto-restart completed across attached devices.")
    except Exception as e:
        log("ERROR", f"Failed to restart frida-servers: {e}")

def perform_recovery():
    log("WARNING", "Initiating ADB Recovery...")
    procs = get_adb_processes()
    root_pids = [pid for pid, user, _ in procs if user == "root"]
    tech_pids = [pid for pid, user, _ in procs if user == TECH_USER]

    if root_pids:
        kill_processes(root_pids, use_sudo=True)
    if tech_pids:
        kill_processes(tech_pids, use_sudo=False)

    try:
        subprocess.run(["sudo", "killall", "-9", "adb"], stderr=subprocess.DEVNULL)
        subprocess.run(["killall", "-9", "adb"], stderr=subprocess.DEVNULL)
    except: pass

    time.sleep(2)

    try:
        log("INFO", "Starting adb server...")
        env = os.environ.copy()
        env["HOME"] = "/home/tech"
        subprocess.run(["adb", "start-server"], env=env, check=True)
    except Exception as e:
        log("ERROR", f"Failed to start adb server: {e}")
        return False

    success, stdout, stderr = run_adb_cmd(["devices"], timeout_sec=5)
    if success:
        lines = stdout.strip().split("\n")
        device_count = sum(1 for line in lines[1:] if line.strip() and not line.startswith("*"))
        log("SUCCESS", f"ADB server recovered: {device_count} devices attached.")
        restart_frida_servers()
        return True
    else:
        log("ERROR", f"ADB verification failed: {stderr}")
        return False

RECOVERY_LOG_PATH = os.path.join(V2_ROOT, "logs", "adb_recovery.log")

def write_recovery_log(event_type, details):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] [{event_type}] {details}\n"
    try:
        os.makedirs(os.path.dirname(RECOVERY_LOG_PATH), exist_ok=True)
        with open(RECOVERY_LOG_PATH, 'a') as f:
            f.write(log_entry)
        os.chmod(RECOVERY_LOG_PATH, 0o666)
    except Exception as e:
        log("ERROR", f"Failed to write to adb_recovery.log: {e}")

def get_usb_path_by_serial(serial):
    if MANIFEST_AVAILABLE:
        try:
            port = manifest.get_device_usb_port(serial)
            if port and port != "N/A":
                return port.replace("usb:", "")
            
            # Fallback to sysfs scan via manifest API
            port_sysfs = manifest.get_usb_port_via_sysfs(serial)
            if port_sysfs and port_sysfs != "N/A":
                return port_sysfs.replace("usb:", "")
        except: pass
    return None

def reset_usb_device(usb_path):
    unbind_file = "/sys/bus/usb/drivers/usb/unbind"
    bind_file = "/sys/bus/usb/drivers/usb/bind"
    log("INFO", f"Targeting USB port {usb_path} for hardware unbind/bind reset...")
    try:
        res_unbind = subprocess.run(
            ["sudo", "tee", unbind_file],
            input=usb_path.encode(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE
        )
        if res_unbind.returncode == 0:
            log("INFO", f"Sent unbind to {usb_path}")
        else:
            log("ERROR", f"Unbind failed for {usb_path}: {res_unbind.stderr.decode().strip()}")
            return False

        time.sleep(2)

        res_bind = subprocess.run(
            ["sudo", "tee", bind_file],
            input=usb_path.encode(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE
        )
        if res_bind.returncode == 0:
            log("INFO", f"Sent bind to {usb_path}")
            return True
        else:
            log("ERROR", f"Bind failed for {usb_path}: {res_bind.stderr.decode().strip()}")
    except Exception as e:
        log("ERROR", f"Hardware reset error: {e}")
    return False

def check_adb_status():
    procs = get_adb_processes()
    root_pids = [p[0] for p in procs if p[1] == "root"]

    try:
        success, stdout, stderr = run_adb_cmd(["devices"], timeout_sec=ADB_TIMEOUT_SEC)
        if not success:
            return False, f"adb devices failed: {stderr}", [], 0, root_pids
        
        lines = stdout.strip().split("\n")
        device_count = 0
        connected_serials = []
        unauthorized_serials = []
        offline_serials = []
        for line in lines[1:]:
            line = line.strip()
            if not line or line.startswith("*"): continue
            device_count += 1
            parts = line.split()
            if not parts: continue
            serial = parts[0]
            connected_serials.append(serial)
            if "unauthorized" in line:
                unauthorized_serials.append(serial)
            elif "offline" in line:
                offline_serials.append(serial)

        # Detect completely missing devices from devices_manifest.json
        missing_serials = []
        if MANIFEST_AVAILABLE:
            try:
                manifest_data = manifest.load_manifest()
                for serial in manifest_data:
                    # Ignore device if marked as excluded
                    if manifest_data[serial].get("is_excluded", False):
                        continue
                    if serial not in connected_serials:
                        missing_serials.append(serial)
            except Exception as e:
                log("ERROR", f"Failed to check missing devices from manifest: {e}")

        bad_serials = list(set(unauthorized_serials + offline_serials + missing_serials))
        if bad_serials:
            reasons = []
            if unauthorized_serials: reasons.append(f"unauthorized: {unauthorized_serials}")
            if offline_serials: reasons.append(f"offline: {offline_serials}")
            if missing_serials: reasons.append(f"missing: {missing_serials}")
            reason_str = "Problematic/Missing devices: " + ", ".join(reasons)
            return False, reason_str, bad_serials, device_count, root_pids
            
        return True, "OK", [], device_count, root_pids

    except subprocess.TimeoutExpired:
        return False, "adb devices command hung (timeout)", [], 0, root_pids

def main():
    log("INFO", "=== ADB Recovery Monitor Started ===")
    consecutive_failures = 0
    
    while True:
        try:
            is_ok, reason, bad_serials, dev_count, root_pids = check_adb_status()
            
            # Auto-kill root-owned adb processes to prevent permission leaks
            if root_pids:
                log("WARNING", f"Killing root adb processes: {root_pids}")
                kill_processes(root_pids, use_sudo=True)
                
            if is_ok:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                log("WARNING", f"Check failed ({consecutive_failures}/3): {reason}")
                write_recovery_log("FAIL_CHECK", f"Reason: {reason} | Fails: {consecutive_failures}")
                
                # If we have problematic devices, attempt selective reset
                if bad_serials and consecutive_failures >= 2:
                    for serial in bad_serials:
                        usb_path = get_usb_path_by_serial(serial)
                        if usb_path:
                            log("WARNING", f"Triggering hardware reset for device {serial} on USB port {usb_path}...")
                            write_recovery_log("RESET_DEVICE", f"Serial: {serial} | Port: {usb_path}")
                            reset_usb_device(usb_path)
                        else:
                            log("ERROR", f"Could not resolve USB path for {serial}. Skipping reset.")
                            
                # If total adb server hangs, trigger full recovery
                if consecutive_failures >= 3:
                    log("CRITICAL", "3 consecutive failures. Rebuilding adb server...")
                    write_recovery_log("RECOVERY_TRIGGER", "ADB server rebuild triggered")
                    perform_recovery()
                    consecutive_failures = 0
                    
        except Exception as e:
            log("ERROR", f"Loop exception: {e}")
            
        time.sleep(CHECK_INTERVAL_SEC)

if __name__ == "__main__":
    main()

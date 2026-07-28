#!/usr/bin/env python3
import os
import json
import re
import subprocess
import fcntl

V2_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
MANIFEST_PATH = os.path.join(V2_ROOT, "config", "devices_manifest.json")

def get_usb_port_via_sysfs(serial):
    """Scan sysfs to find the physical USB port for a given serial number."""
    try:
        devices_dir = "/sys/bus/usb/devices"
        if os.path.exists(devices_dir):
            for d in os.listdir(devices_dir):
                serial_path = os.path.join(devices_dir, d, "serial")
                if os.path.exists(serial_path):
                    try:
                        with open(serial_path, "r", encoding="utf-8", errors="ignore") as f:
                            val = f.read().strip()
                        if val == serial:
                            return d
                    except: pass
    except: pass
    return "N/A"

def auto_generate_manifest():
    """Discover connected devices, query physical USB ports, assign subnets contiguously, and save the manifest."""
    os.makedirs(os.path.dirname(MANIFEST_PATH), exist_ok=True)
    
    # 1. Get connected adb devices
    connected_serials = []
    try:
        output = subprocess.check_output(["adb", "devices"], timeout=5).decode("utf-8")
        lines = output.strip().split("\n")[1:]
        for line in lines:
            if line.strip() and "device" in line and not line.startswith("*"):
                connected_serials.append(line.split()[0])
    except: pass
    
    connected_serials = sorted(list(set(connected_serials)))
            
    # 2. Load active LTE subnets from network interfaces
    subnets = []
    try:
        output = subprocess.check_output(["ip", "-br", "addr", "show"]).decode("utf-8")
        for line in output.splitlines():
            parts = line.split()
            if parts:
                name = parts[0]
                m = re.match(r'^lte(\d+)$', name)
                if m:
                    subnets.append(int(m.group(1)))
    except: pass
    
    subnets = sorted(list(set(subnets)))
    if not subnets:
        subnets = list(range(11, 21))
        
    # 3. Unify metadata contiguously into blocks (Grouped by Subnet)
    manifest_data = {}
    group_size = len(connected_serials) // len(subnets)
    if group_size == 0:
        group_size = 1
        
    for idx, serial in enumerate(connected_serials):
        usb_port = get_usb_port_via_sysfs(serial)
        
        subnet_idx = idx // group_size
        if subnet_idx >= len(subnets):
            subnet_idx = len(subnets) - 1
        subnet_assigned = subnets[subnet_idx]
        
        manifest_data[serial] = {
            "usb_port": usb_port,
            "subnet": subnet_assigned,
            "is_excluded": False
        }
        
    save_manifest(manifest_data)
    return manifest_data

_MANIFEST_CACHE = None

def load_manifest(auto_create=True, force_refresh=False):
    """Load the devices manifest. Auto-generates it if file is missing."""
    global _MANIFEST_CACHE
    if _MANIFEST_CACHE is not None and not force_refresh:
        return _MANIFEST_CACHE

    if not os.path.exists(MANIFEST_PATH):
        if auto_create:
            _MANIFEST_CACHE = auto_generate_manifest()
            return _MANIFEST_CACHE
        return {}
        
    data = {}
    try:
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Sync with connected devices if new devices are found (auto-healing)
        connected_serials = []
        try:
            output = subprocess.check_output(["adb", "devices"], timeout=5).decode("utf-8")
            lines = output.strip().split("\n")[1:]
            for line in lines:
                if line.strip() and "device" in line and not line.startswith("*"):
                    connected_serials.append(line.split()[0])
        except: pass

        needs_update = any(serial not in data for serial in connected_serials)

        if needs_update and auto_create:
            print("[*] New devices detected. Merging into devices_manifest.json...")
            new_manifest = auto_generate_manifest()
            for k, v in data.items():
                if k in new_manifest:
                    new_manifest[k]["is_excluded"] = v.get("is_excluded", False)
            save_manifest(new_manifest)
            _MANIFEST_CACHE = new_manifest
            return _MANIFEST_CACHE

        _MANIFEST_CACHE = data
        return _MANIFEST_CACHE
    except Exception as e:
        if auto_create:
            _MANIFEST_CACHE = auto_generate_manifest()
            return _MANIFEST_CACHE
        return {}

def save_manifest(data):
    """Safely save manifest dict to JSON file with atomic replacement."""
    global _MANIFEST_CACHE
    try:
        os.makedirs(os.path.dirname(MANIFEST_PATH), exist_ok=True)
        tmp_path = MANIFEST_PATH + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, MANIFEST_PATH)
        _MANIFEST_CACHE = data
        return True
    except Exception as e:
        print(f"[-] Failed to save manifest: {e}")
        return False

# --- API FUNCTIONS FOR DYNAMIC QUERIES ---

def get_ordered_devices(include_offline=True):
    """Get list of serials sorted by subnet group, then alphabetically by serial."""
    data = load_manifest()
    
    connected_serials = []
    if not include_offline:
        try:
            output = subprocess.check_output(["adb", "devices"], timeout=5).decode("utf-8")
            lines = output.strip().split("\n")[1:]
            for line in lines:
                if line.strip() and "device" in line and not line.startswith("*"):
                    connected_serials.append(line.split()[0])
        except: pass
        
    # Sort keys by subnet value first, then alphabetically by serial number (x)
    sorted_serials = sorted(data.keys(), key=lambda x: (data[x].get("subnet", 11), x))
    
    result = []
    for serial in sorted_serials:
        if include_offline or serial in connected_serials:
            result.append(serial)
    return result

def get_device_subnet(serial):
    """Retrieve assigned modem subnet index (int) for a serial."""
    data = load_manifest()
    if serial in data:
        return data[serial].get("subnet", 11)
    return 11

def get_device_usb_port(serial):
    """Retrieve USB port path for a serial (fallback to sysfs if unknown)."""
    data = load_manifest()
    if serial in data:
        port = data[serial].get("usb_port", "N/A")
        if port != "N/A":
            return port
    return get_usb_port_via_sysfs(serial)

def is_device_excluded(serial):
    """Check if device is disabled/excluded from scheduler."""
    data = load_manifest()
    if serial in data:
        return data[serial].get("is_excluded", False)
    return False

def toggle_device_exclusion(serial):
    """Toggle exclusion flag for a device serial and save manifest."""
    data = load_manifest()
    if serial in data:
        data[serial]["is_excluded"] = not data[serial].get("is_excluded", False)
        save_manifest(data)
        return data[serial]["is_excluded"]
    return False

def load_global_config():
    """Loads feature toggle configs from config/global.conf."""
    config = {
        "USE_SUBNET_LOCK": False,
        "STAGGER_DELAY_SEC": 15,
        "STALE_TASK_TIMEOUT": 1200,
        "QOS_GUARD": True,
        "USE_PROXY": True,
        "USE_FRIDA": True,
        "USE_GPS": True,
        "USE_MACRO": True,
        "ENABLE_TRAFFIC_SAVER": False,
        "API_SERVER": "114.207.112.245:8013"
    }
    config_path = os.path.join(V2_ROOT, "config", "global.conf")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                for line in f:
                    if "=" in line and not line.strip().startswith("#"):
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if v.lower() in ["true", "false"]:
                            config[k] = v.lower() == "true"
                        elif v.isdigit():
                            config[k] = int(v)
                        else:
                            config[k] = v
        except:
            pass
    return config

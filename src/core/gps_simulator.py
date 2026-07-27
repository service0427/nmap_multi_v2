#!/usr/bin/env python3
import os
import sys
import json
import glob
import time
import math
import subprocess
import argparse
import re
import gzip
import base64
from datetime import datetime

# Target GPSEmulator package
PKG_NAME = "com.rosteam.gpsemulator"

def get_now():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]

def log_print(msg):
    print(f"[{get_now()}] {msg}")
    sys.stdout.flush()

class RouteDecoder:
    @staticmethod
    def calculate_distance(coords):
        if not coords or len(coords) < 2: return 0.0
        total = 0.0
        for i in range(len(coords) - 1):
            lat1, lon1 = coords[i]; lat2, lon2 = coords[i+1]
            R = 6371.0
            dlat = math.radians(lat2 - lat1); dlon = math.radians(lon2 - lon1)
            a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            total += R * c
        return total

    @staticmethod
    def decode_zigzag(n): return (n >> 1) ^ (-(n & 1))

    @staticmethod
    def decode_json_path(coords_array):
        if not coords_array or len(coords_array) < 2: return []
        pts = []
        curr_x, curr_y = coords_array[0], coords_array[1]
        pts.append([float(curr_y) / 10000000.0, float(curr_x) / 10000000.0])
        for i in range(2, len(coords_array), 2):
            if i + 1 < len(coords_array):
                curr_x += coords_array[i]; curr_y += coords_array[i+1]
                pts.append([float(curr_y) / 10000000.0, float(curr_x) / 10000000.0])
        return pts

    @classmethod
    def decode_pbf_path(cls, resp_content_raw):
        try:
            if isinstance(resp_content_raw, str):
                if resp_content_raw.startswith("base64:"):
                    resp_content = base64.b64decode(resp_content_raw.split("base64:")[1])
                else:
                    resp_content = resp_content_raw.encode("latin-1", "replace")
                    if len(resp_content) < 10: 
                        resp_content = resp_content_raw.encode("utf-8", "ignore")
            else:
                resp_content = resp_content_raw
            if resp_content and resp_content[:2] == b"\x1f\x8b": 
                resp_content = gzip.decompress(resp_content)
        except Exception: return []
        if not resp_content: return []
        for i in range(len(resp_content) - 10):
            if resp_content[i] == 0x0a:
                try:
                    idx = i + 1; length = 0; shift = 0
                    while idx < len(resp_content):
                        b = resp_content[idx]; idx += 1
                        length |= (b & 0x7f) << shift
                        shift += 7
                        if not (b & 0x80): break
                    if 10 < length < 2000000 and idx + length <= len(resp_content):
                        arr = resp_content[idx:idx+length]; idx2 = 0; coords = []
                        while idx2 < len(arr):
                            val = 0; s2 = 0
                            while idx2 < len(arr):
                                b = arr[idx2]; idx2 += 1
                                val |= (b & 0x7f) << s2
                                s2 += 7
                                if not (b & 0x80): break
                            coords.append(cls.decode_zigzag(val))
                        if len(coords) >= 4:
                            lng_sample, lat_sample = coords[0], coords[1]
                            if 1200000000 < lng_sample < 1350000000 and 300000000 < lat_sample < 450000000:
                                return cls.decode_json_path(coords)
                except Exception: pass
        return []

def get_su_cmd(device_id):
    try:
        res = subprocess.run(["adb", "-s", device_id, "shell", "which su"], capture_output=True, text=True, timeout=5).stdout.strip()
        if res and "not found" not in res:
            return res
    except: pass
    for path in ["/system/bin/su", "/system/xbin/su", "/sbin/su"]:
        try:
            res = subprocess.run(["adb", "-s", device_id, "shell", f"ls {path}"], capture_output=True, text=True, timeout=5).stdout.strip()
            if res and "No such" not in res:
                return path
        except: pass
    return "su"

def set_static_location(device_id, lat, lng):
    """Injects static coords directly to GPSEmulator preferences."""
    dev_tmp_dir = f"/home/tech/nmap_multi_v2/logs/devices/{device_id}/tmp"
    os.makedirs(dev_tmp_dir, exist_ok=True)
    local_xml = os.path.join(dev_tmp_dir, "static_prefs.xml")
    
    with open(local_xml, "w", encoding="utf-8") as f:
        f.write(f"<?xml version='1.0' encoding='utf-8' standalone='yes' ?>\n<map>\n")
        f.write(f'    <boolean name="noads" value="true" />\n')
        f.write(f'    <boolean name="onettimeblock" value="true" />\n')
        f.write(f'    <int name="pagbookmark" value="1" />\n')
        f.write(f'    <int name="accion" value="0" />\n')
        f.write(f'    <float name="velocidad" value="0.0" />\n')
        f.write(f'    <string name="ruta0">Parking+1+0.0+0.0+{lat},{lng};{lat},{lng};</string>\n')
        f.write(f'    <string name="lastloc">Current+{lat},{lng}+15.0</string>\n')
        f.write(f"</map>")
        
    prefs_path = f"/data/data/{PKG_NAME}/shared_prefs/{PKG_NAME}_preferences.xml"
    subprocess.run(["adb", "-s", device_id, "shell", "am", "force-stop", PKG_NAME], capture_output=True)
    subprocess.run(["adb", "-s", device_id, "push", local_xml, "/data/local/tmp/static_gps.xml"], capture_output=True)
    su_cmd = get_su_cmd(device_id)
    subprocess.run(["adb", "-s", device_id, "shell", su_cmd, "-c",
                    f"cp /data/local/tmp/static_gps.xml {prefs_path} && chown $(stat -c %u:%g /data/data/{PKG_NAME}) {prefs_path} && chmod 660 {prefs_path} && rm /data/local/tmp/static_gps.xml"], capture_output=True)
    
    # Start continuous simulation at speed 0
    cmd = ["adb", "-s", device_id, "shell", su_cmd, "-c", 
           f"am start-foreground-service -n {PKG_NAME}/.servicex2484 -a ACTION_START_CONTINUOUS --es uy.digitools.RUTA 'ruta0' --ef velocidad 0.0 --ei loopMode 1"]
    subprocess.run(cmd, capture_output=True)
    try:
        os.remove(local_xml)
    except: pass
    log_print(f"[✓] [{device_id}] Static GPS set at {lat}, {lng}")

def set_simulator_speed(device_id, kmh):
    speed_mps = round(kmh / 3.6, 4)
    speed_mps = max(speed_mps, 0.8333) # 3.0 km/h floor
    su_cmd = get_su_cmd(device_id)
    cmd = ["adb", "-s", device_id, "shell", su_cmd, "-c", 
           f"am start-foreground-service -n {PKG_NAME}/.servicex2484 -a ACTION_START_CONTINUOUS --es uy.digitools.RUTA 'ruta0' --ef velocidad {speed_mps} --ei loopMode 0"]
    subprocess.run(cmd, capture_output=True)
    log_print(f"[*] [🚀] Speed Adjusted: {kmh} km/h (m/s: {speed_mps})")

def move_gps_to_target(device_id, target_lat, target_lng):
    """Force teleport GPS emulator to target end coordinates."""
    log_print(f"[🛡️] SAFETY TRIGGER: Force Teleporting GPS to Target: {target_lat}, {target_lng}")
    set_static_location(device_id, target_lat, target_lng)

def trigger_back_sequence(device_id):
    """Send back key press after arrival."""
    log_print(f"[🛡️] SAFETY TRIGGER: Sending 'Back' key event to Naver Map app.")
    subprocess.run(["adb", "-s", device_id, "shell", "input", "keyevent", "4"], capture_output=True)
    time.sleep(15)

def get_latest_driving_packet(log_dir):
    pattern = os.path.join(log_dir, "**/*_GET_v3_global_driving.json")
    files = glob.glob(pattern, recursive=True)
    if not files: return None
    try:
        files.sort(key=lambda x: int(os.path.basename(x).split('_')[0]), reverse=True)
        return files[0]
    except: return None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", required=True)
    parser.add_argument("--log-dir", required=False)
    parser.add_argument("--arrival-time", type=int, default=300)
    parser.add_argument("--static-lat", type=float)
    parser.add_argument("--static-lng", type=float)
    args = parser.parse_args()

    # Just set static coordinates and exit if flags are passed
    if args.static_lat and args.static_lng:
        set_static_location(args.device, args.static_lat, args.static_lng)
        sys.exit(0)

    if not args.log_dir:
        log_print("[-] Error: --log-dir is required for dynamic simulation mode.")
        sys.exit(1)

    # Dynamic route update simulation main loop
    log_print(f"[*] Starting GPS simulation agent for device {args.device}")
    
    total_target_sec = args.arrival_time
    session_start_ts = time.time()
    driving_start_ts = None
    
    active_xml_path = None
    xml_hash = ""
    
    while True:
        # Check parent runner process alive
        # If lock file disappears, stop simulator
        lock_file = f"/home/tech/nmap_multi_v2/logs/devices/{args.device}/tmp/nmap_lock"
        if not os.path.exists(lock_file):
            log_print("[*] Lock file removed. Stopping GPS Simulation.")
            break
            
        latest_packet = get_latest_driving_packet(args.log_dir)
        if not latest_packet:
            time.sleep(2)
            continue
            
        # Check if packet changed by hashing it
        try:
            with open(latest_packet, "rb") as f:
                curr_hash = hashlib.md5(f.read()).hexdigest()
        except:
            time.sleep(2)
            continue
            
        if curr_hash == xml_hash:
            # Check elapsed safety exit
            if driving_start_ts:
                elapsed_driving = time.time() - driving_start_ts
                if elapsed_driving >= total_target_sec + 30:
                    log_print(f"[!] Target drive duration reached ({total_target_sec}s). Shutting down.")
                    break
            time.sleep(2)
            continue
            
        # Parse route path
        try:
            with open(latest_packet, "r", encoding="utf-8") as f:
                packet_data = json.load(f)
            
            resp = packet_data.get("response", {})
            body_str = resp.get("body", "")
            
            # Decode coordinates
            coords = RouteDecoder.decode_pbf_path(body_str)
            if not coords:
                log_print("[-] FAILED: RouteDecoder could not decode coordinates from driving packet.")
                xml_hash = curr_hash
                time.sleep(2)
                continue
                
            total_dist_km = RouteDecoder.calculate_distance(coords)
            log_print(f"[✓] Successfully parsed route path. Points: {len(coords)} | Distance: {total_dist_km:.2f} km")
            
            # Calculate target speed
            speed_kmh = round((total_dist_km / (total_target_sec / 3600.0)), 2)
            # Enforce constraints (min 20, max 95 km/h)
            speed_kmh = max(20.0, min(95.0, speed_kmh))
            
            log_print(f"[*] Target Simulation Speed: {speed_kmh} km/h")
            
            # Rebuild XML and push to emulator
            dev_tmp_dir = f"/home/tech/nmap_multi_v2/logs/devices/{args.device}/tmp"
            os.makedirs(dev_tmp_dir, exist_ok=True)
            local_xml = os.path.join(dev_tmp_dir, "route_prefs.xml")
            
            # Format RUTA string
            ruta_pts = []
            for lat, lng in coords:
                ruta_pts.append(f"{lat},{lng}")
            ruta_str = ";".join(ruta_pts) + ";"
            
            with open(local_xml, "w", encoding="utf-8") as f:
                f.write(f"<?xml version='1.0' encoding='utf-8' standalone='yes' ?>\n<map>\n")
                f.write(f'    <boolean name="noads" value="true" />\n')
                f.write(f'    <boolean name="onettimeblock" value="true" />\n')
                f.write(f'    <int name="pagbookmark" value="1" />\n')
                f.write(f'    <int name="accion" value="2" />\n')
                f.write(f'    <float name="velocidad" value="{round(speed_kmh / 3.6, 4)}" />\n')
                f.write(f'    <string name="ruta0">Parking+1+0.0+0.0+{ruta_str}</string>\n')
                f.write(f'    <string name="lastloc">Current+{coords[0][0]},{coords[0][1]}+15.0</string>\n')
                f.write(f"</map>")
                
            prefs_path = f"/data/data/{PKG_NAME}/shared_prefs/{PKG_NAME}_preferences.xml"
            subprocess.run(["adb", "-s", args.device, "shell", "am", "force-stop", PKG_NAME], capture_output=True)
            subprocess.run(["adb", "-s", args.device, "push", local_xml, "/data/local/tmp/route_gps.xml"], capture_output=True)
            su_cmd = get_su_cmd(args.device)
            subprocess.run(["adb", "-s", args.device, "shell", su_cmd, "-c",
                            f"cp /data/local/tmp/route_gps.xml {prefs_path} && chown $(stat -c %u:%g /data/data/{PKG_NAME}) {prefs_path} && chmod 660 {prefs_path} && rm /data/local/tmp/route_gps.xml"], capture_output=True)
            
            # Start service simulation
            cmd = ["adb", "-s", args.device, "shell", su_cmd, "-c", 
                   f"am start-foreground-service -n {PKG_NAME}/.servicex2484 -a ACTION_START_CONTINUOUS --es uy.digitools.RUTA 'ruta0' --ef velocidad {round(speed_kmh / 3.6, 4)} --ei loopMode 0"]
            subprocess.run(cmd, capture_output=True)
            
            try:
                os.remove(local_xml)
            except: pass
            
            driving_start_ts = time.time()
            xml_hash = curr_hash
            
            # Write dynamic updates to current_task.json
            task_json = f"/home/tech/nmap_multi_v2/logs/devices/{args.device}/current_task.json"
            if os.path.exists(task_json):
                try:
                    with open(task_json, "r") as f:
                        curr_data = json.load(f)
                    curr_data.update({
                        "simulated_speed": speed_kmh,
                        "distance_km": round(total_dist_km, 2),
                        "total_target_sec": total_target_sec,
                        "driving_start_time": datetime.fromtimestamp(driving_start_ts).strftime('%H:%M:%S')
                    })
                    with open(task_json, "w") as f:
                        json.dump(curr_data, f, indent=2, ensure_ascii=False)
                except: pass

        except Exception as e:
            log_print(f"[-] Error parsing route JSON: {e}")
            traceback.print_exc()
            
        time.sleep(5)

import hashlib
import traceback
if __name__ == "__main__":
    main()

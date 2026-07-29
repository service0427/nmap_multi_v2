#!/usr/bin/env python3
import os
import sys
import json
import time
import argparse
import subprocess
import signal
import re
from datetime import datetime
import random

# Ensure we import ADBManager and IdentityAuditEngine
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "macro"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "macro"))
from adb import ADBManager
from reporter import IdentityAuditEngine
import api_client
from lock_manager import DeviceLock
import manifest
import ui_clicker
from executor import MacroExecutor
import type_helper
import glob

API_SERVER = api_client.API_SERVER

class ProxyManager:
    def __init__(self, device_id, mode, task_data):
        self.device_id = device_id
        self.mode = mode
        self.task_data = task_data
        
        self.task_id = task_data.get("task_id")
        self.device_seq = task_data.get("device_seq")
        if self.device_seq is None:
            try:
                ordered_devices = manifest.get_ordered_devices(include_offline=True)
                self.device_seq = ordered_devices.index(self.device_id) + 1 if self.device_id in ordered_devices else 1
            except Exception:
                self.device_seq = 1
        self.dest_id = task_data.get("destination", {}).get("id")
        self.dest_name = task_data.get("destination", {}).get("target_name")
        self.dest_addr = task_data.get("destination", {}).get("address", "")
        self.dest_lat = task_data.get("destination", {}).get("lat")
        self.dest_lng = task_data.get("destination", {}).get("lng")
        
        self.start_pos = task_data.get("start_pos", {})
        self.start_lat = self.start_pos.get("lat")
        self.start_lng = self.start_pos.get("lng")
        self.arrival_time = task_data.get("arrival_time", 300)
        
        # Identity pairs
        self.identity = task_data.get("identity", {})
        self.orig_ssaid = self.identity.get("original", {}).get("ssaid")
        self.orig_adid = self.identity.get("original", {}).get("adid")
        self.orig_idfv = self.identity.get("original", {}).get("idfv")
        self.orig_ni = self.identity.get("original", {}).get("ni")
        self.orig_token = self.identity.get("original", {}).get("token")
        
        self.id_ssaid = self.identity.get("spoofed", {}).get("ssaid")
        self.id_adid = self.identity.get("spoofed", {}).get("adid")
        self.id_idfv = self.identity.get("spoofed", {}).get("idfv")
        self.id_ni = self.identity.get("spoofed", {}).get("ni")
        self.id_token = self.identity.get("spoofed", {}).get("token")

        # Unique port assignments
        self.frida_port = 10000 + int(self.device_seq)
        self.mitm_port = 20000 + int(self.device_seq)
        
        # Logging targets
        self.date_str = datetime.now().strftime("%Y%m%d")
        self.time_str = datetime.now().strftime("%H%M%S")
        self.capture_dir = f"/home/tech/nmap_multi_v2/logs/macro_car/{self.date_str}/{self.device_id}/{self.time_str}_{self.dest_id}"
        os.makedirs(self.capture_dir, exist_ok=True)
        self.exec_log_path = os.path.join(self.capture_dir, "execution.log")
        self.log_file = None

        self.mitm_proc = None
        self.frida_proc = None
        self.gps_proc = None
        self.macro_proc = None
        
        self.bind_ip = None
        self.subnet_idx = None
        self.subnet_lock_file = None
        self.has_subnet_lock = False
        self.config = manifest.load_global_config()

    def log(self, msg):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        log_line = f"[{timestamp}] {msg}\n"
        print(log_line.strip())
        sys.stdout.flush()
        if self.log_file:
            self.log_file.write(log_line)
            self.log_file.flush()

    def update_task_status(self, status, exclude_until=0, extra_data=None):
        task_json = f"/home/tech/nmap_multi_v2/logs/devices/{self.device_id}/current_task.json"
        real_ip_val = getattr(self, "real_ip", None) or self.bind_ip or "LOCAL_WAN"
        data = {
            "status": status,
            "device_seq": self.device_seq,
            "dest_name": self.dest_name,
            "dest_id": self.dest_id,
            "real_ip": real_ip_val,
            "task_id": self.task_id,
            "exclude_until": exclude_until
        }
        if extra_data:
            data.update(extra_data)
        try:
            with open(task_json, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except: pass

    def report_api_status(self, status, message):
        try:
            real_ip_val = getattr(self, "real_ip", None) or self.bind_ip or "LOCAL_WAN"
            api_client.update_status(self.task_id, self.device_id, status, real_ip_val, message)
        except: pass

    def check_battery_safety(self):
        batt = ADBManager.get_battery_level(self.device_id)
        if batt < 20:
            self.log(f"[🚨] BATTERY CRITICAL: {batt}% (Threshold < 20%). Aborting task.")
            self.cleanup(f"BATTERY_LOW_{batt}%")
            sys.exit(1)
            
        temp = ADBManager.get_battery_temp(self.device_id)
        ram = ADBManager.get_free_ram(self.device_id)
        self.log(f"[📊] Battery Status: {batt}% | Temp: {temp}°C | Free RAM: {ram}")

    def clean_naver_map_cache(self):
        self.log("[🧹] Performing smart cache purge (preserving offline tiles & WebView compile cache)...")
        ADBManager.run_adb(self.device_id, "shell am force-stop com.nhn.android.nmap")
        
        # Su command clean up
        su_cmd = get_su_cmd(self.device_id)
        clean_script = (
            "rm -rf /data/data/com.nhn.android.nmap/app_webview/Default/Cookies* "
            "/data/data/com.nhn.android.nmap/app_webview/Default/Local\\ Storage "
            "/data/data/com.nhn.android.nmap/app_webview/Default/Session\\ Storage "
            "/data/data/com.nhn.android.nmap/app_webview/Default/Preferences* "
            "/data/data/com.nhn.android.nmap/databases "
            "/data/data/com.nhn.android.nmap/shared_prefs "
            "/data/data/com.nhn.android.nmap/no_backup/* "
            "/data/data/com.nhn.android.nmap/code_cache/*; "
            "find /data/data/com.nhn.android.nmap/cache/ -maxdepth 1 ! -name 'cache' ! -name 'WebView' -exec rm -rf {} +; "
            "find /data/data/com.nhn.android.nmap/files/ -maxdepth 1 ! -name 'files' ! -name 'NaverNavi' ! -name 'naviguide' -exec rm -rf {} +;"
        )
        ADBManager.run_adb(self.device_id, f"shell \"{su_cmd} -c '{clean_script}'\"")

    def grant_permissions(self):
        self.log("[🛡️] Granting application permissions...")
        permissions = [
            "android.permission.ACCESS_FINE_LOCATION",
            "android.permission.ACCESS_COARSE_LOCATION",
            "android.permission.READ_PHONE_STATE",
            "android.permission.POST_NOTIFICATIONS",
            "android.permission.RECORD_AUDIO"
        ]
        for perm in permissions:
            ADBManager.run_adb(self.device_id, f"shell pm grant com.nhn.android.nmap {perm}")
        ADBManager.run_adb(self.device_id, "shell appops set com.nhn.android.nmap SYSTEM_ALERT_WINDOW allow")

    def inject_golden_template(self):
        self.log("[🧼] Injecting surgical golden preferences template...")
        rand_days = datetime.now().day
        target_date = f"2026-06-{rand_days:02d}"
        
        dev_tmp_dir = f"/home/tech/nmap_multi_v2/logs/devices/{self.device_id}/tmp"
        os.makedirs(dev_tmp_dir, exist_ok=True)
        
        # Build Consent XML
        consent_content = f'<?xml version="1.0" encoding="utf-8"?><map><string name="PREF_CONSENT_GUEST_MAP_TERMS_AGREEMENT_STATUS">{target_date}</string><string name="PREF_CONSENT_GUEST_LOCATION_TERMS_AGREEMENT_STATUS">{target_date}</string><string name="PREF_CONSENT_GUEST_MAP_LOCATION_TERMS_AGREEMENT_STATUS">{target_date}</string><boolean name="PREF_CONSENT_CLOVA_CHECKED" value="true" /><boolean name="PREF_CONSENT_CLOVA_AGREED" value="true" /><boolean name="PREF_CONSENT_NEW_MAP_LOCATION_TERMS_AGREED" value="true" /></map>'
        with open(os.path.join(dev_tmp_dir, "ConsentInfo.xml"), "w") as f:
            f.write(consent_content)
            
        # Build Prefs XML
        prefs_content = '<?xml version="1.0" encoding="utf-8"?><map><boolean name="PREF_NOT_FIRST_RUN" value="true"/><boolean name="THEME_CHANGE_POPUP_NEVER_SHOW_AGAIN" value="true" /><int name="LAUNCHER_TAB_INDEX" value="1" /><boolean name="HIPASS_POPUP_SHOWN" value="true" /><int name="PREF_ROUTE_TYPE" value="2" /><int name="LAST_USED_MODE" value="1" /><boolean name="INTERNAL_NAVI_UUID_PERSONAL_ROUTE_TERMS_AGREED" value="true" /></map>'
        with open(os.path.join(dev_tmp_dir, "prefs.xml"), "w") as f:
            f.write(prefs_content)
            
        # Build NaviDefaults XML
        navi_content = '<?xml version="1.0" encoding="utf-8"?><map><boolean name="NaviUseHipassKey" value="true" /><int name="NaviCarTypeKey" value="1" /><int name="NaviOilTypeKey" value="1" /><boolean name="NaviGuideTrafficCamKey" value="false" /><boolean name="NaviAutoChangeRoute" value="true" /></map>'
        with open(os.path.join(dev_tmp_dir, "navi.xml"), "w") as f:
            f.write(navi_content)
            
        # Randomize volume properties (5~15)
        rand_vol = random.randint(5, 15)
        # Randomize navigation view mode (0: 2D, 2: 3D)
        rand_view = random.choice([0, 2])
        # Build NaviSettings XML (Enabling sound in UI via GUIDE_TYPE=1 with random volume levels in PREF_NAVI_VOLUME)
        settings_content = f"<?xml version='1.0' encoding='utf-8' standalone='yes' ?>\n<map>\n    <int name=\"PREF_SETTING_USE_NIGHT_THEME\" value=\"0\" />\n    <boolean name=\"PREF_SETTING_AUTO_QUIT\" value=\"true\" />\n    <boolean name=\"PREF_ENABLE_ROUTE_LAYER_TRAFFIC\" value=\"true\" />\n    <int name=\"PREF_SETTING_GUIDE_TYPE\" value=\"1\" />\n    <int name=\"PREF_NAVI_EFFECT_VOLUME\" value=\"{rand_vol}\" />\n    <int name=\"PREF_SETTING_NAVI_SYMBOL_SCALE\" value=\"0\" />\n    <int name=\"PREF_SETTING_NAVI_MAP_MODE\" value=\"0\" />\n    <boolean name=\"PREF_ENABLE_SPOTIFY_PLAYER\" value=\"false\" />\n    <int name=\"PREF_SETTING_NAVI_VIEW_MODE\" value=\"{rand_view}\" />\n    <int name=\"PREF_NAVI_VOLUME\" value=\"{rand_vol}\" />\n</map>"
        with open(os.path.join(dev_tmp_dir, "navisettings.xml"), "w") as f:
            f.write(settings_content)

        pkg = "com.nhn.android.nmap"
        su_cmd = get_su_cmd(self.device_id)
        ADBManager.run_adb(self.device_id, f"shell \"{su_cmd} -c 'mkdir -p /data/data/{pkg}/shared_prefs'\"")
        
        ADBManager.run_adb(self.device_id, f"push {os.path.join(dev_tmp_dir, 'ConsentInfo.xml')} /data/local/tmp/ConsentInfo.xml")
        ADBManager.run_adb(self.device_id, f"push {os.path.join(dev_tmp_dir, 'prefs.xml')} /data/local/tmp/prefs.xml")
        ADBManager.run_adb(self.device_id, f"push {os.path.join(dev_tmp_dir, 'navi.xml')} /data/local/tmp/navi.xml")
        ADBManager.run_adb(self.device_id, f"push {os.path.join(dev_tmp_dir, 'navisettings.xml')} /data/local/tmp/navisettings.xml")
        
        # Inject properties and move preference files
        app_uid, _, _ = ADBManager.run_adb(self.device_id, f"shell \"pm list packages -U {pkg} | grep -oE 'uid:[0-9]+' | cut -d: -f2 | head -n 1\"")
        app_uid = app_uid.strip()
        if not app_uid:
            app_uid = "root"
            
        shared_prefs_cmds = (
            f"cp /data/local/tmp/ConsentInfo.xml /data/data/{pkg}/shared_prefs/ && "
            f"cp /data/local/tmp/prefs.xml /data/data/{pkg}/shared_prefs/com.nhn.android.nmap_preferences.xml && "
            f"cp /data/local/tmp/navi.xml /data/data/{pkg}/shared_prefs/NativeNaviDefaults.xml && "
            f"cp /data/local/tmp/navisettings.xml /data/data/{pkg}/shared_prefs/NaviSettingsInfo.xml && "
            f"chown -R {app_uid}:{app_uid} /data/data/{pkg}/shared_prefs && "
            f"chmod -R 777 /data/data/{pkg}/shared_prefs && "
            f"restorecon -R /data/data/{pkg} && "
            f"setprop debug.nmap.ssaid {self.id_ssaid} && "
            f"setprop debug.nmap.idfv {self.id_idfv} && "
            f"setprop debug.nmap.adid {self.id_adid}"
        )
        ADBManager.run_adb(self.device_id, f"shell \"{su_cmd} -c '{shared_prefs_cmds}'\"")
        
        # Clean up files from host and /data/local/tmp
        for filename in ['ConsentInfo.xml', 'prefs.xml', 'navi.xml', 'navisettings.xml']:
            try:
                os.remove(os.path.join(dev_tmp_dir, filename))
            except: pass
            ADBManager.run_adb(self.device_id, f"shell rm -f /data/local/tmp/{filename}")

    def verify_network_ip(self):
        """Verifies actual outbound internet connectivity and queries public external IP."""
        if self.mode == "local":
            self.real_ip = "LOCAL_WAN"
            self.bind_ip = None
            self.log(f"[🌐] Local routing mode active (Bypassing host PBR constraints).")
            return

        # 1. Query actual external IP from inside the device first (True network validation)
        self.log(f"[🌐] Querying external public IP from inside device {self.device_id}...")
        device_ip = ADBManager.get_device_external_ip(self.device_id)
        if device_ip:
            self.log(f"[✓] Real Device External IPv4 verified: {device_ip}")
            self.real_ip = device_ip
        else:
            self.log(f"[⚠️] Failed to query external IP from inside device. Fallback validation.")
            self.real_ip = "LOCAL_WAN"

        # 2. Resolve interface binding if running in 'eth' PBR mode
        self.bind_ip = ADBManager.get_bind_ip(self.device_id, mode="eth")
        self.log(f"[🌐] Resolving LTE dynamic route for {self.device_id} -> BIND_IP: {self.bind_ip}")
        if self.bind_ip:
            import re
            m = re.search(r"\.([0-9]+)\.[0-9]+$", self.bind_ip)
            if m:
                self.subnet_idx = m.group(1)
        
        # Verify network is alive on BIND_IP from host
        ip_ready = False
        for attempt in range(1, 4):
            # Test external curl from host interface
            res = subprocess.run(
                f"curl --interface {self.bind_ip} -s -m 5 http://ifconfig.me", 
                shell=True, capture_output=True, text=True
            )
            real_ip = res.stdout.strip()
            if real_ip and real_ip.split('.')[0].isdigit():
                self.log(f"[✓] Host interface routing verified. Outbound IP: {real_ip}")
                self.real_ip = real_ip
                ip_ready = True
                break
            self.log(f"[⚠️] Network timeout on host interface {self.bind_ip}. Retrying ({attempt}/3)...")
            time.sleep(2)
            
        if not ip_ready and not device_ip:
            # Write gate failure flag to trigger 180s cooldown in scheduler
            ip_failed_gate = f"/home/tech/nmap_multi_v2/logs/devices/{self.device_id}/tmp/ip_failed_gate"
            os.makedirs(os.path.dirname(ip_failed_gate), exist_ok=True)
            with open(ip_failed_gate, "w") as f: f.write("FAIL")
            self.cleanup("NETWORK_TIMEOUT")
            sys.exit(1)
            
        # Write real_ip to session_summary.json so Web Monitor dashboard renders the public cellular IP
        try:
            summary_path = os.path.join(self.capture_dir, "session_summary.json")
            summary_data = {}
            if os.path.exists(summary_path):
                with open(summary_path, "r", encoding="utf-8") as sf:
                    summary_data = json.load(sf)
            summary_data["real_ip"] = self.real_ip
            with open(summary_path, "w", encoding="utf-8") as sf:
                json.dump(summary_data, sf, ensure_ascii=False, indent=2)
        except: pass

    def execute_task(self):
        self.dev_lock = DeviceLock(self.device_id)
        if not self.dev_lock.acquire():
            print(f"[-] Device {self.device_id} is already locked by another process. Exiting.")
            sys.exit(1)
            
        # Create nmap_lock file to signal sub-processes (like gps_simulator.py) that we are running
        dev_tmp_dir = f"/home/tech/nmap_multi_v2/logs/devices/{self.device_id}/tmp"
        os.makedirs(dev_tmp_dir, exist_ok=True)
        self.nmap_lock_path = os.path.join(dev_tmp_dir, "nmap_lock")
        try:
            open(self.nmap_lock_path, "w").close()
        except: pass
            
        self.log_file = open(self.exec_log_path, "a")
        
        # Save api_response.json inside session log
        with open(os.path.join(self.capture_dir, "api_response.json"), "w") as f:
            json.dump(self.task_data, f, indent=2, ensure_ascii=False)
            
        # 1. Environment Snapshot
        self.check_battery_safety()
        self.verify_network_ip()
        
        # Report status IP_CHANGED to central API
        self.report_api_status("IP_CHANGED", f"Real IP verified: {getattr(self, 'real_ip', 'LOCAL_WAN')}")
        self.update_task_status("LAUNCHING")

        # 2. Purge & Ingest
        self.clean_naver_map_cache()
        self.grant_permissions()
        self.inject_golden_template()
        # Randomize Android system media volume database values to look human-like
        # 1. Force mute ALL physical phone audio streams (0~5) & ringer mode to SILENT (0)
        for s_idx in range(6):
            ADBManager.run_adb(self.device_id, f"shell media volume --stream {s_idx} --set 0")
        ADBManager.run_adb(self.device_id, "shell settings put system volume_music 0")
        ADBManager.run_adb(self.device_id, "shell settings put system volume_alarm 0")
        ADBManager.run_adb(self.device_id, "shell settings put system volume_system 0")
        ADBManager.run_adb(self.device_id, "shell settings put system volume_notification 0")
        ADBManager.run_adb(self.device_id, "shell settings put system mode_ringer 0")
        ADBManager.run_adb(self.device_id, "shell cmd audio set-ringer-mode 0")
        # Enable Global Do Not Disturb (DND Total Silence mode - zen_mode 2) to block Speed Camera Sonification Bypass Audio
        ADBManager.run_adb(self.device_id, "shell settings put global zen_mode 2")
        ADBManager.run_adb(self.device_id, "shell cmd notification set_dnd on")
        # Ensure system display theme and density remain stable
        # ADBManager.run_adb(self.device_id, "shell cmd uimode night yes")
        # ADBManager.run_adb(self.device_id, "shell wm density reset")

        # 3. Forwards & Reverse Proxy Tunnels
        if self.config.get("USE_FRIDA", True):
            # Pre-flight check: Ensure frida-server is running on the device
            frida_pid, _, _ = ADBManager.run_adb(self.device_id, "shell pidof frida-server")
            if not frida_pid.strip():
                ADBManager.run_adb(self.device_id, "shell su -c '/system/bin/frida-server &'")
                time.sleep(1)
            ADBManager.run_adb(self.device_id, f"forward --remove tcp:{self.frida_port}")
            ADBManager.run_adb(self.device_id, f"forward tcp:{self.frida_port} tcp:27042")
        # Disable captive portal checks
        ADBManager.run_adb(self.device_id, "shell settings put global captive_portal_mode 0")
        ADBManager.run_adb(self.device_id, "shell settings put global captive_portal_detection_enabled 0")

        # 4. Spawn mitmdump in background first
        if self.config.get("USE_PROXY", True):
            self.log(f"[*] Starting mitmdump on port {self.mitm_port}...")
            # Kill any stale mitmdump process listening on this port
            subprocess.run(f"pkill -9 -f 'mitmdump.*-p {self.mitm_port}'", shell=True)
            time.sleep(0.3)
            
            addon_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mitm", "addon.py"))
            mitm_args = ["mitmdump", "-p", str(self.mitm_port), "-s", addon_path, "--ssl-insecure", "--listen-host", "0.0.0.0", "--set", "flow_detail=0"]
            if self.bind_ip:
                mitm_args.extend(["--set", f"connect_addr={self.bind_ip}"])
                
            env = os.environ.copy()
            env.update({
                "NMAP_ORIG_SSAID": self.orig_ssaid or "",
                "NMAP_ORIG_ADID": self.orig_adid or "",
                "NMAP_ORIG_IDFV": self.orig_idfv or "",
                "NMAP_ORIG_NI": self.orig_ni or "",
                "NMAP_ORIG_TOKEN": self.orig_token or "",
                "NMAP_ID_SSAID": self.id_ssaid or "",
                "NMAP_ID_ADID": self.id_adid or "",
                "NMAP_ID_IDFV": self.id_idfv or "",
                "NMAP_ID_NI": self.id_ni or "",
                "NMAP_ID_TOKEN": self.id_token or "",
                "NMAP_DEV_ID": self.device_id,
                "CAPTURE_LOG_DIR": self.capture_dir,
                "API_SERVER": API_SERVER,
                "NMAP_REAL_IP": getattr(self, "real_ip", None) or self.bind_ip or "LOCAL_WAN",
                "ENABLE_TRAFFIC_SAVER": str(self.config.get("ENABLE_TRAFFIC_SAVER", False)).lower()
            })
            
            mitm_log = open(os.path.join(self.capture_dir, "mitm.log"), "w")
            self.mitm_proc = subprocess.Popen(mitm_args, env=env, stdout=mitm_log, stderr=mitm_log)
            time.sleep(0.5)

            # Establish reverse proxy tunnel and activate device HTTP proxy AFTER mitmdump is active
            ADBManager.run_adb(self.device_id, f"reverse --remove tcp:{self.mitm_port}")
            ADBManager.run_adb(self.device_id, f"reverse tcp:{self.mitm_port} tcp:{self.mitm_port}")
            ADBManager.run_adb(self.device_id, f"shell settings put global http_proxy localhost:{self.mitm_port}")

        # 5. Spawn GPS Simulator path tracker in background
        if self.config.get("USE_GPS", True):
            self.log(f"[*] Initializing static starting coordinates: {self.start_lat}, {self.start_lng}")
            subprocess.run([
                "python3", "/home/tech/nmap_multi_v2/src/core/gps_simulator.py",
                "--device", self.device_id,
                "--static-lat", str(self.start_lat),
                "--static-lng", str(self.start_lng)
            ])
            
            self.log(f"[*] Spawning GPS path simulator (Arrival time: {self.arrival_time}s)...")
            gps_log = open(os.path.join(self.capture_dir, "gps_simulation.log"), "w")
            self.gps_proc = subprocess.Popen([
                "python3", "/home/tech/nmap_multi_v2/src/core/gps_simulator.py",
                "--device", self.device_id,
                "--log-dir", self.capture_dir,
                "--arrival-time", str(self.arrival_time)
            ], stdout=gps_log, stderr=gps_log)

        # 6. Unlock Keyguard
        self.log(f"[*] Dismissing screen keyguard...")
        ADBManager.dismiss_keyguard(self.device_id)

        # 7. Start Naver Map App
        self.log(f"[*] Launching Naver Map...")
        ADBManager.run_adb(self.device_id, "shell am start -n com.nhn.android.nmap/com.naver.map.LaunchActivity")

        # Poll for Map pid
        pid = None
        for i in range(20):
            out, _, _ = ADBManager.run_adb(self.device_id, "shell pidof com.nhn.android.nmap")
            pids = out.strip().split()
            if pids:
                pid = pids[0]
                break
            if i in [5, 12]:
                self.log("  [*] Retrying am start for Naver Map...")
                ADBManager.run_adb(self.device_id, "shell am start -n com.nhn.android.nmap/com.naver.map.LaunchActivity")
            time.sleep(1)
            
        if not pid:
            self.cleanup("App Launch Timeout")
            sys.exit(1)
            
        # 8. Start Frida client attachment
        if self.config.get("USE_FRIDA", True):
            self.log(f"[✓] Naver Map is running (PID: {pid}). Attaching Frida instrumentation hooks...")
            time.sleep(3)
            frida_log = open(os.path.join(self.capture_dir, "frida.log"), "w")
            version_out, _, _ = ADBManager.run_adb(self.device_id, "shell getprop ro.build.version.release")
            android_version = int(version_out.strip().split('.')[0]) if version_out.strip().split('.')[0].isdigit() else 13
            
            frida_script = "/home/tech/nmap_multi_v2/src/frida/network_hook.js"
            if android_version >= 14:
                self.log(f"[*] Android 14+ detected. Loading APEX Conscrypt adapter bypass hooks...")
                frida_script_arg = [
                    "-l", "/home/tech/nmap_multi_v2/src/frida/network_hook.js",
                    "-l", "/home/tech/nmap_multi_v2/src/frida/core_survival.js",
                    "-l", "/home/tech/nmap_multi_v2/src/frida/version_adapters/android_14_15.js"
                ]
            else:
                frida_script_arg = [
                    "-l", "/home/tech/nmap_multi_v2/src/frida/network_hook.js",
                    "-l", "/home/tech/nmap_multi_v2/src/frida/core_survival.js",
                    "-l", "/home/tech/nmap_multi_v2/src/frida/version_adapters/android_12_13.js"
                ]

            frida_args = ["frida", "-H", f"localhost:{self.frida_port}", "--runtime=v8", "-p", str(pid), "--no-auto-reload", "-q", "-t", "inf"]
            frida_args.extend(frida_script_arg)
            self.frida_proc = subprocess.Popen(frida_args, stdout=frida_log, stderr=frida_log)

        # 9. Launch Macro Actions Executor
        if self.config.get("USE_MACRO", True):
            self.log(f"[*] Initializing macro state actions executor...")
            # We run the macro state machine directly inside monitor_loop, so we don't spawn it as subprocess
            self.macro_proc = None

        # 10. Core execution loop monitoring
        self.monitor_loop()

    def get_events(self):
        events_path = os.path.join(self.capture_dir, "events.log")
        if not os.path.exists(events_path):
            return []
        try:
            with open(events_path, "r", encoding="utf-8") as f:
                return [line.strip() for line in f if line.strip()]
        except:
            return []

    def report_live_status(self, status):
        try:
            payload = {
                "task_id": int(self.task_id) if str(self.task_id).isdigit() else self.task_id,
                "status": status,
                "device_id": self.device_id
            }
            self.log(f"[API_REQ] /api/v1/update_status -> {json.dumps(payload, ensure_ascii=False)}")
            success, response = api_client.update_status(
                task_id=self.task_id,
                device_id=self.device_id,
                status=status,
                real_ip=getattr(self, 'real_ip', 'LOCAL_WAN'),
                message=""
            )
            self.log(f"[API_RES] {response}\nHTTP_CODE:200" if success else f"[API_RES] {response}\nHTTP_CODE:500")
        except Exception as e:
            self.log(f"[-] Failed to update live status: {e}")

    def monitor_loop(self):
        self.log("[*] Task execution monitoring loop started.")
        
        # Set CAPTURE_LOG_DIR in environment for ui_clicker
        os.environ["CAPTURE_LOG_DIR"] = self.capture_dir
        
        # Macro State Machine Variables
        state_flags = {
            "STEP_02_HOME": 0,
            "STEP_03_TYPING": 0,
            "STEP_04_SELECT_ADDR": 0,
            "STEP_05_POI_ARRIVAL": 0,
            "STEP_07_NAVI_START": 0,
            "STEP_07_1_BUSINESS_MODAL": 0,
            "STEP_07_2_DRIVING_STARTED": 0,
            "STEP_08_DRIVING_GOAL": 0,
            "STEP_09_FINISH": 1
        }
        is_driving = False
        start_ts = time.time()
        last_home_check_ts = time.time()
        last_ui_check_ts = time.time()
        arrival_click_fail_count = 0
        last_survival_check_ts = time.time()
        
        while True:
            now = time.time()

            # A. Basic Process Survival Checks (Matching V1 exact 15-second check interval)
            if now - last_survival_check_ts >= 15:
                last_survival_check_ts = now
                map_status, _, _ = ADBManager.run_adb(self.device_id, "shell pidof com.nhn.android.nmap")
                if not map_status.strip():
                    self.app_closed_count = getattr(self, "app_closed_count", 0) + 1
                    if self.app_closed_count >= 3:
                        devices = ADBManager.get_connected_devices()
                        if self.device_id in devices:
                            events = self.get_events()
                            has_routeend = any("routeend" in evt.lower() for evt in events) or len(glob.glob(os.path.join(self.capture_dir, "*routeend*.json"))) > 0
                            if has_routeend:
                                self.log("[✓] Verified routeend packet before app close. Reporting SUCCESS!")
                                self.cleanup("Task Completed")
                            else:
                                self.log("[!] App Closed by system/user (3 consecutive retries).")
                                self.cleanup("App Closed")
                            break
                else:
                    self.app_closed_count = 0
                        
                # 2. Check Frida connection (Hooks remain active in memory when CLI detaches)
                if self.config.get("USE_FRIDA", True) and self.frida_proc:
                    if self.frida_proc.poll() is not None:
                        self.log("[ℹ️] Frida client CLI detached (hooks remain active in memory). Session continuing...")
                        self.frida_proc = None
                        
                # 3. Check mitmproxy
                if self.config.get("USE_PROXY", True) and self.mitm_proc:
                    if self.mitm_proc.poll() is not None:
                        self.log("[!] mitmdump proxy crash detected.")
                        self.cleanup("mitmdump Crash (Proxy stopped)")
                        break

            # B. Macro State Machine (Event-driven UI Automation)
            if self.config.get("USE_MACRO", True):
                events = self.get_events()
                
                # Auto-heal ADB reverse proxy tunnel if dropped by ADB daemon re-enumeration
                if self.config.get("USE_PROXY", True) and (now - getattr(self, "last_reverse_check_ts", 0) >= 5):
                    self.last_reverse_check_ts = now
                    rev_list, _, _ = ADBManager.run_adb(self.device_id, "reverse --list")
                    if str(self.mitm_port) not in rev_list:
                        ADBManager.run_adb(self.device_id, f"reverse tcp:{self.mitm_port} tcp:{self.mitm_port}")
                        ADBManager.run_adb(self.device_id, f"shell settings put global http_proxy localhost:{self.mitm_port}")

                # Global Fast Recovery for Fatal UI / Dismiss Popups (Matching V1 exact 30s check interval)
                if now - last_ui_check_ts >= 30:
                    last_ui_check_ts = now
                    xml_file, _ = ui_clicker.get_ui_dump_pair(self.device_id, "check_fatal")
                    now = time.time()  # Refresh timestamp after UI dump delay
                    if xml_file:
                        try:
                            with open(xml_file, "r", encoding="utf-8", errors="ignore") as f_check:
                                dump_text = f_check.read()
                            if ("네이버지도 검색" in dump_text or "btn_home_search" in dump_text) and state_flags["STEP_02_HOME"] == 0:
                                self.log("[✓] Home screen search bar found in XML dump. Marking Home ready.")
                                state_flags["STEP_02_HOME"] = 1
                                step1_home_ts = now
                        except: pass

                        # 1. Check fatal UI errors
                        is_fatal, fatal_text = ui_clicker.check_fatal_errors(xml_file)
                        if is_fatal:
                            self.log(f"[🚨] Fatal UI State Detected: '{fatal_text}'. Fail-fast.")
                            self.cleanup(f"NO_ROUTE_FOUND: {fatal_text}")
                            break
                        # 2. Automatically dismiss cache popups
                        ui_clicker.check_and_dismiss_popups(self.device_id, xml_file, "AutoDismiss")
                        try:
                            os.remove(xml_file)
                        except: pass

                # Refresh current timestamp before step evaluations
                now = time.time()

                # routeend detection
                if state_flags["STEP_08_DRIVING_GOAL"] == 0:
                    if any("routeend" in evt.lower() for evt in events):
                        self.log("[🌟] CASE: routeend detected! Finalizing session.")
                        state_flags["STEP_07_2_DRIVING_STARTED"] = 1
                        state_flags["STEP_08_DRIVING_GOAL"] = 1

                # Step 1: Home screen and search field click
                if state_flags["STEP_02_HOME"] == 0:
                    # Dual Trigger: nlogapp packet event 'home' OR 3.0s elapsed since app launch
                    if any("home" in evt.lower() for evt in events) or (now - start_ts > 3.0):
                        self.log("[✓] Home screen UI elements detected. Tapping search field.")
                        self.report_live_status("HOME_READY")
                        success = MacroExecutor.run_step(self.device_id, "entry_search_field", category="01.SearchAndNavi")
                        if success:
                            state_flags["STEP_02_HOME"] = 1
                            step1_home_ts = now
                        elif now - start_ts > 15:
                            if now - last_home_check_ts >= 10:
                                last_home_check_ts = now
                                self.log(f"[⚠️] Failed to reach Home search field within {int(now - start_ts)}s. Dismissing popups...")
                                MacroExecutor.run_step(self.device_id, "exact:닫기", category="DismissPopup")
                                MacroExecutor.run_step(self.device_id, "exact:확인", category="DismissPopup")
                                MacroExecutor.run_step(self.device_id, "exact:나중에 하기", category="DismissPopup")
                                ADBManager.run_adb(self.device_id, "shell am start -n com.nhn.android.nmap/com.naver.map.LaunchActivity")

                # Step 2: Typing search keyword
                elif state_flags["STEP_03_TYPING"] == 0:
                    step1_elapsed = (now - step1_home_ts) if 'step1_home_ts' in locals() else 99
                    if any("sch.all.entry" in evt.lower() for evt in events) or step1_elapsed > 1.0:
                        self.log(f"[Action] Typing destination keyword: {self.dest_name}")
                        self.report_live_status("SEARCHING")
                        type_helper.type_humanized(self.device_id, self.dest_name)
                        self.log("    > Waiting 8s for recommendation list...")
                        time.sleep(8)
                        state_flags["STEP_03_TYPING"] = 1

                # Step 3: Select Address List
                elif state_flags["STEP_04_SELECT_ADDR"] == 0:
                    # Acquire Subnet Lock if enabled
                    if self.config.get("USE_SUBNET_LOCK", False) and self.subnet_idx and not getattr(self, "has_subnet_lock", False):
                        self.log(f"[🔒] Subnet Lock enabled. Waiting for lock on subnet_{self.subnet_idx}...")
                        lock_dir = "/home/tech/nmap_multi_v2/logs/locks"
                        os.makedirs(lock_dir, exist_ok=True)
                        lock_path = os.path.join(lock_dir, f"subnet_{self.subnet_idx}_run.lock")
                        try:
                            self.subnet_lock_file = open(lock_path, "w")
                            import fcntl
                            fcntl.flock(self.subnet_lock_file, fcntl.LOCK_EX)
                            self.has_subnet_lock = True
                            self.subnet_lock_acquired_ts = time.time()
                            self.log(f"[🔓] Subnet Lock acquired on subnet_{self.subnet_idx}!")
                        except Exception as lock_err:
                            self.log(f"[⚠️] Failed to acquire subnet lock: {lock_err}")

                    self.log("[Action] Selecting address from search list...")
                    self.report_live_status("SELECTING_DEST")
                    
                    # Bypass check: if POI detail card is already open with '도착' button visible
                    poi_open = False
                    xml_file, _ = ui_clicker.get_ui_dump_pair(self.device_id, "check_poi_open")
                    if xml_file:
                        try:
                            with open(xml_file, "r", encoding="utf-8", errors="ignore") as f:
                                xml_content = f.read()
                            if 'text="도착"' in xml_content or 'content-desc="도착"' in xml_content:
                                self.log("[✓] POI Detail sheet is already open. Skipping address selection.")
                                poi_open = True
                        except: pass
                        try: os.remove(xml_file)
                        except: pass
                        
                    if poi_open:
                        state_flags["STEP_04_SELECT_ADDR"] = 1
                        continue

                    # Wait for loading indicator to disappear (up to 10s)
                    for wait_sec in range(10):
                        xml_file, _ = ui_clicker.get_ui_dump_pair(self.device_id, "check_loading")
                        if xml_file:
                            try:
                                with open(xml_file, "r", encoding="utf-8", errors="ignore") as f:
                                    xml_content = f.read()
                                if "v_loading_component" not in xml_content and "v_loading_image" not in xml_content:
                                    try: os.remove(xml_file)
                                    except: pass
                                    break
                            except: pass
                            try: os.remove(xml_file)
                            except: pass
                        self.log("    > Search results are loading... waiting 1s.")
                        time.sleep(1)

                    # Clean address suffixes
                    cleaned_addr = ""
                    for word in self.dest_addr.split():
                        if any(word.endswith(x) for x in ["층", "호", "실", "동"]) or word.startswith("("):
                            break
                        cleaned_addr += " " + word
                    cleaned_addr = cleaned_addr.strip().rstrip(",").strip()
                    
                    self.log(f"    > Clicking address: '{cleaned_addr}' (Original: {self.dest_addr})")
                    success = MacroExecutor.run_step(self.device_id, f"contains:{cleaned_addr}", category="01.SearchAndNavi")
                    if not success:
                        self.log(f"    > Cleaned address failed. Retrying with original: {self.dest_addr}")
                        success = MacroExecutor.run_step(self.device_id, f"contains:{self.dest_addr}", category="01.SearchAndNavi")
                        
                    if not success:
                        self.log("    > Address text not matched directly. Tapping top recommendation result item...")
                        success = MacroExecutor.run_step(self.device_id, "entry_search_result_item", category="01.SearchAndNavi") or \
                                  MacroExecutor.run_step(self.device_id, "exact:도착", category="01.SearchAndNavi")

                    if not success:
                        self.log("[🚨] Failure Reason: ADDRESS_NOT_FOUND (Fail-fast)")
                        self.cleanup("ADDRESS_NOT_FOUND")
                        break
                        
                    state_flags["STEP_04_SELECT_ADDR"] = 1

                # Step 4: Click '도착' (POI info view)
                elif state_flags["STEP_05_POI_ARRIVAL"] == 0:
                    has_poi_event = any("poi.end" in evt.lower() for evt in events)
                    has_arrival_btn = False
                    xml_file, _ = ui_clicker.get_ui_dump_pair(self.device_id, "check_arrival_btn")
                    if xml_file:
                        try:
                            with open(xml_file, "r", encoding="utf-8", errors="ignore") as f:
                                xml_content = f.read()
                            if 'text="도착"' in xml_content or 'content-desc="도착"' in xml_content:
                                has_arrival_btn = True
                        except: pass
                        try: os.remove(xml_file)
                        except: pass
                        
                    if has_poi_event or has_arrival_btn:
                        self.log("[Action] Clicking '도착' (POI Arrival)...")
                        self.report_live_status("CONFIRM_ARRIVAL")
                        success = MacroExecutor.run_step(self.device_id, "exact:도착", category="01.SearchAndNavi")
                        if success:
                            state_flags["STEP_05_POI_ARRIVAL"] = 1
                            time.sleep(5)
                        else:
                            arrival_click_fail_count += 1
                            self.log(f"[⚠️] Failed to click '도착' (Fail Count: {arrival_click_fail_count}/3)")
                            if arrival_click_fail_count >= 3:
                                self.log("[🚨] '도착' button not found after 3 attempts. Aborting.")
                                self.cleanup("POI_ARRIVAL_NOT_FOUND")
                                break

                # Step 5: Click '안내시작'
                elif state_flags["STEP_07_NAVI_START"] == 0:
                    has_route_event = any("drt.route.car" in evt.lower() for evt in events)
                    has_start_btn = False
                    xml_file, _ = ui_clicker.get_ui_dump_pair(self.device_id, "check_start_btn")
                    if xml_file:
                        try:
                            with open(xml_file, "r", encoding="utf-8", errors="ignore") as f:
                                xml_content = f.read()
                            if '안내시작' in xml_content or 'btn_start_guidance' in xml_content:
                                has_start_btn = True
                        except: pass
                        try: os.remove(xml_file)
                        except: pass
                        
                    if has_route_event or has_start_btn:
                        self.log("[Action] Clicking '안내시작' (Guidance Start)...")
                        self.report_live_status("STARTING_NAVI")
                        success = MacroExecutor.run_step(self.device_id, "btn_start_guidance", category="01.SearchAndNavi")
                        if success:
                            state_flags["STEP_07_NAVI_START"] = 1
                            state_flags["STEP_07_2_DRIVING_STARTED"] = 1
                            self.report_live_status("DRIVING")
                        else:
                            self.log("[🚨] '안내시작' button not found. Aborting.")
                            self.cleanup("GUIDANCE_NOT_FOUND")
                            break

                # Step 6: Handle warning popup modal
                elif state_flags["STEP_07_1_BUSINESS_MODAL"] == 0 and any("businesshourwarningmodalfragment" in evt.lower() for evt in events):
                    self.log("[Action] Business hour warning modal detected. Dismissing...")
                    MacroExecutor.run_step(self.device_id, "btn_start_guidance_modal", category="01.SearchAndNavi")
                    state_flags["STEP_07_1_BUSINESS_MODAL"] = 1

                # Step 7: Drive initialization
                elif state_flags["STEP_07_2_DRIVING_STARTED"] == 0:
                    drive_trigger = False
                    if self.config.get("QOS_GUARD", True):
                        if any("navi.drivemode" in evt.lower() for evt in events):
                            drive_trigger = True
                    else:
                        if any("global/driving" in evt.lower() for evt in events):
                            drive_trigger = True
                            
                    if drive_trigger:
                        self.log("[Action] Driving active. Marking path simulator status.")
                        self.report_live_status("DRIVING")
                        is_driving = True
                        try:
                            # Touch guidance_started file for signaling
                            open(os.path.join(self.capture_dir, "guidance_started"), "w").close()
                        except: pass
                        state_flags["STEP_07_2_DRIVING_STARTED"] = 1
                    else:
                        # [Self-Healing] If navigation start was clicked but driving didn't activate within 20s, check if we need to tap '안내시작' again
                        now = time.time()
                        if state_flags["STEP_07_NAVI_START"] == 1:
                            if not hasattr(self, "last_navi_retry_ts"):
                                self.last_navi_retry_ts = now
                            if now - self.last_navi_retry_ts > 20:
                                self.last_navi_retry_ts = now
                                self.log("[🔧 Self-Healing] Navigation clicked but driving not started. Checking for '안내시작' button...")
                                xml_file, _ = ui_clicker.get_ui_dump_pair(self.device_id, "check_start_btn")
                                if xml_file:
                                    try:
                                        with open(xml_file, "r", encoding="utf-8", errors="ignore") as f:
                                            xml_content = f.read()
                                        if '안내시작' in xml_content or 'btn_start_guidance' in xml_content:
                                            self.log("[🔧 Self-Healing] Clicking '안내시작' again...")
                                            MacroExecutor.run_step(self.device_id, "btn_start_guidance", category="01.SearchAndNavi")
                                    except: pass
                                    try: os.remove(xml_file)
                                    except: pass

                # Step 8: Drive ending and click '안내종료'
                elif state_flags["STEP_08_DRIVING_GOAL"] == 1:
                    self.log("[Action] Arrival complete. Stopping GPS and sending click '안내종료'...")
                    self.report_live_status("ARRIVED")
                    
                    # Kill GPS Emulator process
                    if self.gps_proc and self.gps_proc.poll() is None:
                        try: self.gps_proc.kill()
                        except: pass
                        
                    MacroExecutor.run_step(self.device_id, "exact:안내종료", category="01.SearchAndNavi")
                    state_flags["STEP_08_DRIVING_GOAL"] = 2  # Mark as fully ended
                    state_flags["STEP_09_FINISH"] = 0

                # Step 9: Finalizing driving result and clean exit
                elif state_flags["STEP_09_FINISH"] == 0:
                    self.log("[Action] Goal reached. Waiting 10s for final logs verification...")
                    self.report_live_status("FINISHING")
                    time.sleep(10)
                    
                    # 1. Verify mandatory routeend packet presence (matching V1 monitor.sh lines 634-641)
                    events = self.get_events()
                    has_routeend_evt = any("routeend" in evt.lower() for evt in events) or len(glob.glob(os.path.join(self.capture_dir, "*routeend*.json"))) > 0
                    
                    # 2. Extract actual driving distance and time from trafficjam / global_driving packets
                    actual_dist = 0
                    actual_time = 0
                    trafficjam_files = glob.glob(os.path.join(self.capture_dir, "*_trafficjam*.json")) + glob.glob(os.path.join(self.capture_dir, "*_global_driving*.json"))
                    for f in trafficjam_files:
                        try:
                            with open(f, "r", encoding="utf-8", errors="ignore") as tf:
                                tdata = json.load(tf)
                                d = tdata.get("request", {}).get("body", {}).get("_decoded", {}).get("1", {}).get("12", 0)
                                t = tdata.get("request", {}).get("body", {}).get("_decoded", {}).get("1", {}).get("13", 0)
                                if d > 0 and t > 0:
                                    actual_dist = d
                                    actual_time = t
                        except: pass

                    if not has_routeend_evt:
                        self.log("[🚨] SUCCESS VERIFICATION FAILED: Missing routeend packet.")
                        self.cleanup("MISSING_ARRIVAL_PACKETS: routeend log missing")
                        break
                    else:
                        self.log(f"[✓] Verified mandatory routeend packet & trafficjam movement (Dist: {actual_dist}m, Time: {actual_time}s). Reporting SUCCESS!")
                        state_flags["STEP_09_FINISH"] = 1
                        self.cleanup("Task Completed")
                        break
            # Dynamic Subnet Lock Release
            if getattr(self, "has_subnet_lock", False):
                elapsed = time.time() - self.subnet_lock_acquired_ts
                if state_flags["STEP_07_2_DRIVING_STARTED"] == 1 or elapsed >= 80:
                    try:
                        import fcntl
                        fcntl.flock(self.subnet_lock_file, fcntl.LOCK_UN)
                        self.subnet_lock_file.close()
                    except: pass
                    self.subnet_lock_file = None
                    self.has_subnet_lock = False
                    self.log(f"[🔓] Subnet Lock released dynamically (Elapsed: {int(elapsed)}s).")
            
            time.sleep(2)

    def cleanup(self, reason):
        self.log(f"[*] Performing cleanup. Reason: {reason}")
        
        # Release subnet lock if held
        if getattr(self, "has_subnet_lock", False) and self.subnet_lock_file:
            try:
                import fcntl
                fcntl.flock(self.subnet_lock_file, fcntl.LOCK_UN)
                self.subnet_lock_file.close()
            except: pass
            self.subnet_lock_file = None
            self.has_subnet_lock = False
            self.log("[🔓] Subnet Lock released during cleanup.")
        
        # 1. Kill background subprocesses
        for proc in [self.mitm_proc, self.frida_proc, self.gps_proc, self.macro_proc]:
            if proc and proc.poll() is None:
                try:
                    proc.kill()
                except: pass
                
        # 2. Remove locks and restore settings
        ADBManager.run_adb(self.device_id, "shell am force-stop com.nhn.android.nmap")
        ADBManager.run_adb(self.device_id, "shell settings put global http_proxy :0")
        ADBManager.run_adb(self.device_id, f"forward --remove tcp:{self.frida_port}")
        ADBManager.run_adb(self.device_id, f"reverse --remove tcp:{self.mitm_port}")
        
        if hasattr(self, 'dev_lock') and self.dev_lock:
            self.dev_lock.release()
            
        task_json = f"/home/tech/nmap_multi_v2/logs/devices/{self.device_id}/current_task.json"
        try:
            os.remove(task_json)
        except: pass
            
        if hasattr(self, 'nmap_lock_path') and self.nmap_lock_path:
            try:
                os.remove(self.nmap_lock_path)
            except: pass
            
        # 3. Run Post-Run Audit and Rotator Scoring Engine
        self.log("[*] Spawning Identity Laundering post-run Audit Engine...")
        try:
            leaked = IdentityAuditEngine.audit_and_score(
                self.capture_dir, self.device_id, self.task_id, reason
            )
            if leaked:
                self.log("[🚨🚨🚨] FORCING TASK RESULT TO 'FAIL' DUE TO ANONYMITY LEAK!")
                self.report_api_status("FAIL", f"IDENTITY_LEAK_DETECTED ({reason})")
                payload = {"task_id": self.task_id, "status": "FAIL", "device_id": self.device_id, "message": f"IDENTITY_LEAK_DETECTED ({reason})"}
                self.log(f"[API_REQ] /api/v1/report_result -> {json.dumps(payload, ensure_ascii=False)}")
                success, response = api_client.report_result(self.task_id, self.device_id, "FAIL", f"IDENTITY_LEAK_DETECTED ({reason})")
                self.log(f"[API_RES] {response}\nHTTP_CODE:200" if success else f"[API_RES] {response}\nHTTP_CODE:500")
            else:
                if reason == "Task Completed":
                    self.log("[✓] Session completed successfully.")
                    self.report_api_status("SUCCESS", "정상 도착 및 클릭 완료")
                    extra_json = {}
                    dist_m = self.start_pos.get("dist_m", 0)
                    arr_sec = self.arrival_time
                    if dist_m > 0 and arr_sec > 0:
                        calc_speed = round((dist_m / 1000.0) / (arr_sec / 3600.0), 2)
                        extra_json = {
                            "drive_dist": int(dist_m),
                            "drive_time": int(arr_sec),
                            "calc_speed": calc_speed
                        }
                    payload = {"task_id": self.task_id, "status": "SUCCESS", "device_id": self.device_id, "message": "정상 도착 및 클릭 완료"}
                    if extra_json: payload.update(extra_json)
                    self.log(f"[API_REQ] /api/v1/report_result -> {json.dumps(payload, ensure_ascii=False)}")
                    success, response = api_client.report_result(self.task_id, self.device_id, "SUCCESS", "정상 도착 및 클릭 완료", extra_json)
                    self.log(f"[API_RES] {response}\nHTTP_CODE:200" if success else f"[API_RES] {response}\nHTTP_CODE:500")
                else:
                    status = "FAIL"
                    if reason in ["ADDRESS_NOT_FOUND", "App Closed"]:
                        status = "API_ERROR"
                    self.report_api_status(status, reason)
                    payload = {"task_id": self.task_id, "status": status, "device_id": self.device_id, "message": str(reason)}
                    self.log(f"[API_REQ] /api/v1/report_result -> {json.dumps(payload, ensure_ascii=False)}")
                    success, response = api_client.report_result(self.task_id, self.device_id, status, reason)
                    self.log(f"[API_RES] {response}\nHTTP_CODE:200" if success else f"[API_RES] {response}\nHTTP_CODE:500")
        except Exception as e:
            self.log(f"[-] Audit execution error: {e}")
            
        if self.log_file:
            self.log_file.close()

def get_su_cmd(device_id):
    return ADBManager.run_adb(device_id, "shell which su")[0].strip() or "su"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", required=True)
    parser.add_argument("--mode", required=True)
    parser.add_argument("--task-data", required=True)
    args = parser.parse_args()
    
    task_data = json.loads(args.task_data)
    manager = ProxyManager(args.device, args.mode, task_data)
    manager.execute_task()

if __name__ == "__main__":
    main()

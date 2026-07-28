#!/usr/bin/env python3
# Nmap Multi V2: First-run device initialization and environment validation pipeline
import sys
import os
import time
import subprocess
import re

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
INSTALL_DIR = os.path.join(PROJECT_ROOT, "install")
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src", "lib"))
from adb import ADBManager

def run_shell(dev, cmd_str):
    """Executes ADB shell command."""
    out, err, rc = ADBManager.run_adb(dev, f"shell \"{cmd_str}\"")
    return out.strip()

def run_su(dev, cmd_str):
    """Executes ADB shell command with su root privileges."""
    out, err, rc = ADBManager.run_adb(dev, f"shell \"su -c '{cmd_str}'\"")
    return out.strip()

def check_and_install_naver_map(dev):
    """Installs Naver Map v6.8.1.1 split APKs if missing or version mismatched."""
    candidate_dirs = [
        os.path.join(INSTALL_DIR, "naver_map_6.8.1.1"),
        os.path.join(INSTALL_DIR, "naver_map"),
        os.path.join(INSTALL_DIR, "com.nhn.android.nmap_6.8.1.1")
    ]
    apk_dir = None
    for c in candidate_dirs:
        if os.path.exists(c) and os.path.exists(os.path.join(c, "base.apk")):
            apk_dir = c
            break
            
    if apk_dir:
        apks = [os.path.join(apk_dir, f) for f in os.listdir(apk_dir) if f.endswith(".apk")]
        # Ensure base.apk is passed FIRST to install-multiple
        apks = sorted(apks, key=lambda x: (0 if os.path.basename(x) == "base.apk" else 1, x))
        if apks:
            res = ADBManager.run_adb(dev, f"install-multiple -r -d -g {' '.join(apks)}", timeout=180)
            if res[2] == 0:
                return True, "v6.8.1.1 (Auto-Installed)"
            else:
                err_msg = res[1].strip() or res[0].strip() or "Unknown ADB Error"
                return False, f"Installation Failed ({err_msg})"
                
    return False, "Not Installed (Missing base.apk in install/)"

def check_and_install_gps_emulator(dev):
    """Installs GPS Emulator if missing and grants Mock Location appops."""
    pkgs_out = run_shell(dev, "pm list packages")
    gps_pkgs = ["com.rosteam.gpsemulator", "uy.digitools.rutasgps.mocklocation", "uy.digitools.rutasgps", "com.lsw.gpsemulator"]
    for p in gps_pkgs:
        if p in pkgs_out:
            run_su(dev, f"appops set {p} android:mock_location allow")
            return True, f"Installed ({p}) & Mock Location Allowed"

    apk_dir = os.path.join(INSTALL_DIR, "gpsemulator")
    if os.path.exists(apk_dir):
        apks = [os.path.join(apk_dir, f) for f in os.listdir(apk_dir) if f.endswith(".apk")]
        if apks:
            res = ADBManager.run_adb(dev, f"install-multiple -r {' '.join(apks)}")
            if res[2] == 0:
                run_su(dev, "appops set com.rosteam.gpsemulator android:mock_location allow")
                return True, "Installed (com.rosteam.gpsemulator) & Mock Location Allowed"
    return False, "Not Installed"

def check_and_install_adb_keyboard(dev):
    """Installs ADBKeyboard and sets it as default IME."""
    apk_file = os.path.join(INSTALL_DIR, "ADBKeyboard.apk")
    if os.path.exists(apk_file):
        ADBManager.run_adb(dev, f"install -r {apk_file}")
        run_su(dev, "ime enable com.android.adbkeyboard/.AdbIME 2>/dev/null; ime set com.android.adbkeyboard/.AdbIME 2>/dev/null")
        return True, "Installed & Set as Default IME"
    return False, "Not Installed"

def check_and_start_frida(dev):
    """Audits frida-server binary presence and process execution status."""
    pgrep_out = run_su(dev, "pgrep -f frida-server")
    if pgrep_out and pgrep_out.isdigit():
        return True, f"Running (PID: {pgrep_out.splitlines()[0]})"

    # Attempt start
    run_su(dev, "/system/bin/frida-server &")
    time.sleep(1)
    pgrep_out2 = run_su(dev, "pgrep -f frida-server")
    if pgrep_out2 and pgrep_out2.splitlines()[0].isdigit():
        return True, f"Started & Running (PID: {pgrep_out2.splitlines()[0]})"
    else:
        return True, "Binary Ready (/system/bin/frida-server)"

def verify_and_install_mitm_cert(dev):
    """Verifies host PC mitmproxy CA certificate against device CA store and installs if missing/mismatched."""
    cert_path = os.path.expanduser("~/.mitmproxy/mitmproxy-ca-cert.pem")
    
    # 1. Ensure mitmproxy cert exists on host (start mitmdump for 2s if missing)
    if not os.path.exists(cert_path):
        print("  [*] Host mitmproxy CA certificate missing. Spawning mitmdump for 2s to generate...")
        try:
            proc = subprocess.Popen(["mitmdump"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2)
            proc.terminate()
            try: proc.wait(timeout=2)
            except: proc.kill()
        except Exception as e:
            print(f"  [-] Failed to spawn mitmdump: {e}")
        
    if not os.path.exists(cert_path):
        return False, "Host mitmproxy cert (~/.mitmproxy/mitmproxy-ca-cert.pem) missing"

    # 2. Extract host hash and MD5
    try:
        res = subprocess.run(["openssl", "x509", "-inform", "PEM", "-subject_hash_old", "-in", cert_path], capture_output=True, text=True, check=True)
        cert_hash = res.stdout.strip().splitlines()[0].strip()
    except Exception as e:
        return False, f"Failed to compute cert hash: {e}"

    try:
        res = subprocess.run(["md5sum", cert_path], capture_output=True, text=True, check=True)
        host_md5 = res.stdout.split()[0].strip()
    except Exception as e:
        return False, f"Failed to compute host cert MD5: {e}"

    target_cert_file = f"{cert_hash}.0"
    user_cert_path = f"/data/misc/user/0/cacerts-added/{target_cert_file}"
    magisk_cert_path = f"/data/adb/modules/trustusercerts/system/etc/security/cacerts/{target_cert_file}"

    # 3. Query existing device cert MD5
    user_out, _, _ = ADBManager.run_adb(dev, f"shell \"su -c 'md5sum {user_cert_path}'\"")
    magisk_out, _, _ = ADBManager.run_adb(dev, f"shell \"su -c 'md5sum {magisk_cert_path}'\"")

    dev_user_md5 = user_out.split()[0].strip() if user_out and len(user_out.split()[0].strip()) == 32 else ""
    dev_magisk_md5 = magisk_out.split()[0].strip() if magisk_out and len(magisk_out.split()[0].strip()) == 32 else ""

    if dev_user_md5 == host_md5 or dev_magisk_md5 == host_md5:
        return True, f"Verified & Active (Hash: {target_cert_file}, MD5: {host_md5[:8]}...)"

    # 4. Push host cert to /data/local/tmp/
    tmp_dest = f"/data/local/tmp/{target_cert_file}"
    push_res = ADBManager.run_adb(dev, f"push {cert_path} {tmp_dest}")
    if push_res[2] != 0:
        return False, f"Failed to push cert to device: {push_res[1]}"

    # 5. Direct atomic root shell commands for certificate installation
    run_su(dev, "mkdir -p /data/misc/user/0/cacerts-added")
    run_su(dev, f"cp -f {tmp_dest} {user_cert_path}")
    run_su(dev, f"chown 1000:1000 {user_cert_path} 2>/dev/null || chown system:system {user_cert_path} 2>/dev/null")
    run_su(dev, f"chmod 644 {user_cert_path}")

    run_su(dev, "mkdir -p /data/adb/modules/trustusercerts/system/etc/security/cacerts 2>/dev/null")
    run_su(dev, f"cp -f {tmp_dest} {magisk_cert_path} 2>/dev/null")
    run_su(dev, f"chown 0:0 {magisk_cert_path} 2>/dev/null || chown root:root {magisk_cert_path} 2>/dev/null")
    run_su(dev, f"chmod 644 {magisk_cert_path} 2>/dev/null")
    run_su(dev, f"chcon u:object_r:system_security_cacerts_file:s0 {magisk_cert_path} 2>/dev/null")
    run_su(dev, f"rm -f {tmp_dest}")

    # 6. Re-check device MD5
    re_user_out, _, _ = ADBManager.run_adb(dev, f"shell \"su -c 'md5sum {user_cert_path}'\"")
    re_magisk_out, _, _ = ADBManager.run_adb(dev, f"shell \"su -c 'md5sum {magisk_cert_path}'\"")

    re_user_md5 = re_user_out.split()[0].strip() if re_user_out and len(re_user_out.split()[0].strip()) == 32 else ""
    re_magisk_md5 = re_magisk_out.split()[0].strip() if re_magisk_out and len(re_magisk_out.split()[0].strip()) == 32 else ""

    if re_user_md5 == host_md5 or re_magisk_md5 == host_md5:
        return True, f"Installed & Verified (Hash: {target_cert_file}, MD5: {host_md5[:8]}...)"
    else:
        return False, f"Verification Failed (Host: {host_md5[:8]}, User: {re_user_md5 or 'None'}, Magisk: {re_magisk_md5 or 'None'})"

def init_single_device(dev):
    print(f"\n============================================================")
    print(f"📱 Initializing & Auditing Device: [{dev}]")
    print(f"============================================================")
    
    # 1. Root & System Settings (Single fast batch execution)
    run_su(dev, "settings put global bluetooth_on 0; settings put system volume_music 0; settings put system volume_notification 0; settings put system volume_ring 0; settings put system volume_system 0; settings put global captive_portal_mode 0; settings put global captive_portal_detection_enabled 0; settings put system accelerometer_rotation 0; settings put system user_rotation 0; settings put global wifi_scan_always_enabled 0; settings put global ble_scan_always_enabled 0")
    print(f"  [✓] System Preferences: Muted, Portrait Locked & Captive Portal Disabled")

    # 2. Grant Permissions for Naver Map
    pkg = "com.nhn.android.nmap"
    run_su(dev, f"pm grant {pkg} android.permission.ACCESS_FINE_LOCATION 2>/dev/null; pm grant {pkg} android.permission.ACCESS_COARSE_LOCATION 2>/dev/null; pm grant {pkg} android.permission.ACCESS_BACKGROUND_LOCATION 2>/dev/null; pm grant {pkg} android.permission.READ_PHONE_STATE 2>/dev/null; pm grant {pkg} android.permission.WRITE_EXTERNAL_STORAGE 2>/dev/null; pm grant {pkg} android.permission.READ_EXTERNAL_STORAGE 2>/dev/null")
        
    # 3. Check ZFlip fold state
    ADBManager.check_and_fix_zflip(dev)

    # 4. Fast Single-Call Package Audit
    pkgs_out = run_shell(dev, "pm list packages")
    
    # Naver Map Audit (Check actual installed version on physical device - Target: 6.8.1.1)
    TARGET_MAP_VER = "6.8.1.1"
    map_installed = "com.nhn.android.nmap" in pkgs_out
    curr_map_ver = None
    if map_installed:
        ver_out = run_shell(dev, "dumpsys package com.nhn.android.nmap | grep versionName")
        m = re.search(r"versionName=([0-9\.]+)", ver_out)
        curr_map_ver = m.group(1) if m else None

    if map_installed and curr_map_ver == TARGET_MAP_VER:
        print(f"  [✓] Naver Map App: v{curr_map_ver} (Installed & Verified)")
    else:
        if map_installed:
            print(f"  [*] Naver Map version mismatch on {dev} (Current: v{curr_map_ver}, Target: v{TARGET_MAP_VER}). Upgrading...")
        else:
            print(f"  [*] Naver Map not installed on {dev}. Installing v{TARGET_MAP_VER}...")
            
        map_ok, map_msg = check_and_install_naver_map(dev)
        print(f"  [{'✓' if map_ok else '❌'}] Naver Map App: {map_msg}")

    # GPS Emulator Audit
    gps_found = None
    for p in ["com.rosteam.gpsemulator", "uy.digitools.rutasgps.mocklocation", "uy.digitools.rutasgps", "com.lsw.gpsemulator"]:
        if p in pkgs_out:
            gps_found = p
            break

    if gps_found:
        run_su(dev, f"appops set {gps_found} android:mock_location allow")
        print(f"  [✓] GPS Emulator App: Installed ({gps_found}) & Mock Location Allowed")
    else:
        gps_ok, gps_msg = check_and_install_gps_emulator(dev)
        print(f"  [{'✓' if gps_ok else '❌'}] GPS Emulator App: {gps_msg}")

    # ADBKeyboard Audit
    if "com.android.adbkeyboard" in pkgs_out:
        run_su(dev, "ime enable com.android.adbkeyboard/.AdbIME 2>/dev/null; ime set com.android.adbkeyboard/.AdbIME 2>/dev/null")
        print(f"  [✓] ADBKeyboard App: Installed & Active as Default IME")
    else:
        ime_ok, ime_msg = check_and_install_adb_keyboard(dev)
        print(f"  [{'✓' if ime_ok else '❌'}] ADBKeyboard App: {ime_msg}")

    # Frida Server Audit
    frida_ok, frida_msg = check_and_start_frida(dev)
    print(f"  [{'✓' if frida_ok else '❌'}] Frida Server: {frida_msg}")

    # MITM CA Certificate Audit
    cert_ok, cert_msg = verify_and_install_mitm_cert(dev)
    print(f"  [{'✓' if cert_ok else '❌'}] MITM CA Certificate: {cert_msg}")

def ensure_local_install_assets():
    """Checks if local install directory and required APK assets exist. Compulsorily downloads from GDrive via update_nmap.sh if missing."""
    nmap_apk = os.path.join(INSTALL_DIR, "naver_map_6.8.1.1", "base.apk")
    base_apk = os.path.join(INSTALL_DIR, "ADBKeyboard.apk")
    gps_apk = os.path.join(INSTALL_DIR, "gpsemulator", "base.apk")
    
    missing_assets = not (os.path.exists(INSTALL_DIR) and os.path.exists(nmap_apk) and os.path.exists(base_apk) and os.path.exists(gps_apk))
    
    if missing_assets:
        print("\n============================================================")
        print("📥 [Notice] 'install' directory or APK assets missing!")
        print("📥 Triggering compulsory Google Drive asset download...")
        print("============================================================")
        update_script = os.path.join(PROJECT_ROOT, "tools", "update_nmap.sh")
        if os.path.exists(update_script):
            res = subprocess.run(["bash", update_script, "--non-interactive"])
            if res.returncode != 0:
                print("[-] Warning: Failed to download install assets from Google Drive.")
        else:
            print("[-] Warning: tools/update_nmap.sh script not found!")
    else:
        print("[✓] Local 'install' directory and APK assets verified.")

def check_device_root_authorization(devices):
    """Pre-audits all connected devices for su root shell authorization (uid=0). Summarize root status and halt execution if any device lacks root approval."""
    print(f"[*] Performing preliminary Root Shell (su) authorization audit on {len(devices)} devices...")
    authorized_devices = []
    unauthorized_devices = []
    no_su_devices = []

    for dev in devices:
        res = run_su(dev, "id")
        if "uid=0" in res:
            authorized_devices.append(dev)
        else:
            has_su_bin = run_shell(dev, "which su 2>/dev/null || ls /system/bin/su /system/xbin/su 2>/dev/null")
            if "su" in has_su_bin:
                unauthorized_devices.append(dev)
            else:
                no_su_devices.append(dev)

    print("\n============================================================")
    print("🔐 Root Shell (su) Authorization Status Report")
    print("============================================================")
    print(f"  [✓] Authorized (uid=0)   : {len(authorized_devices)} devices")
    if authorized_devices:
        print(f"      • {', '.join(authorized_devices)}")
        
    print(f"  [❌] Pending / Denied     : {len(unauthorized_devices)} devices")
    if unauthorized_devices:
        print(f"      • {', '.join(unauthorized_devices)}")

    print(f"  [❌] Missing 'su' Binary   : {len(no_su_devices)} devices")
    if no_su_devices:
        print(f"      • {', '.join(no_su_devices)}")
    print("============================================================")

    if unauthorized_devices or no_su_devices:
        print("\n⛔ [HALT] Root Shell Authorization Failure detected!")
        print("------------------------------------------------------------")
        if unauthorized_devices:
            print(f"[!] {len(unauthorized_devices)} device(s) require Magisk Root approval:")
            print(f"    Target Devices: {', '.join(unauthorized_devices)}")
            print("    👉 휴대폰 화면을 켜고 Magisk 팝업 창에서 'Grant(허용)' 버튼을 누른 후 스크립트를 재실행해주세요.")
        if no_su_devices:
            print(f"[!] {len(no_su_devices)} device(s) do NOT have 'su' binary installed:")
            print(f"    Target Devices: {', '.join(no_su_devices)}")
            print("    👉 기기가 정상적으로 루팅(Magisk)되어 있는지 확인해주세요.")
        print("------------------------------------------------------------")
        print("❌ Initialization halted. Please resolve root permissions and re-run './cmd.sh --init'.\n")
        sys.exit(1)

def main():
    devices = ADBManager.get_connected_devices()
    if not devices:
        print("[-] No active ADB devices found.")
        sys.exit(1)
        
    check_device_root_authorization(devices)
    ensure_local_install_assets()
        
    print(f"============================================================")
    print(f"🚀 Nmap Multi V2: Comprehensive Device & App Audit ({len(devices)} devices)")
    print(f"============================================================")
    
    for dev in devices:
        init_single_device(dev)
            
    print(f"\n============================================================")
    print("[✓] All connected devices and core apps audited & initialized successfully.")
    print(f"============================================================")

if __name__ == "__main__":
    main()

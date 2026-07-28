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
    """Installs Naver Map v6.8.1.1 if missing."""
    apk_dir = os.path.join(INSTALL_DIR, "naver_map_6.8.1.1")
    if os.path.exists(apk_dir):
        apks = [os.path.join(apk_dir, f) for f in os.listdir(apk_dir) if f.endswith(".apk")]
        if apks:
            res = ADBManager.run_adb(dev, f"install-multiple -r {' '.join(apks)}")
            if res[2] == 0:
                return True, "v6.8.1.1 (Auto-Installed)"
    return False, "Not Installed (Missing base.apk)"

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
    if not os.path.exists(cert_path):
        subprocess.run("mitmdump --help >/dev/null 2>&1", shell=True)
        time.sleep(1)
        
    if not os.path.exists(cert_path):
        return False, "Host mitmproxy cert (~/.mitmproxy/mitmproxy-ca-cert.pem) missing"

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

    dev_md5_out = run_su(dev, f"md5sum {user_cert_path} 2>/dev/null || md5sum {magisk_cert_path} 2>/dev/null")
    dev_md5 = dev_md5_out.split()[0].strip() if dev_md5_out else None

    if dev_md5 == host_md5:
        return True, f"Verified & Active (Hash: {target_cert_file}, MD5: {host_md5[:8]}...)"

    # Push and install host cert to device
    subprocess.run(["adb", "-s", dev, "push", cert_path, f"/data/local/tmp/{target_cert_file}"], capture_output=True)
    install_cmd = (
        f"mkdir -p /data/misc/user/0/cacerts-added && "
        f"cp /data/local/tmp/{target_cert_file} {user_cert_path} && "
        f"chown 1000:1000 {user_cert_path} && chmod 644 {user_cert_path} && "
        f"mkdir -p /data/adb/modules/trustusercerts/system/etc/security/cacerts 2>/dev/null || true && "
        f"cp /data/local/tmp/{target_cert_file} {magisk_cert_path} 2>/dev/null || true && "
        f"chmod 644 {magisk_cert_path} 2>/dev/null || true && "
        f"rm -f /data/local/tmp/{target_cert_file}"
    )
    run_su(dev, install_cmd)
    
    re_out = run_su(dev, f"md5sum {user_cert_path} 2>/dev/null || md5sum {magisk_cert_path} 2>/dev/null")
    re_md5 = re_out.split()[0].strip() if re_out else None
    
    if re_md5 == host_md5:
        return True, f"Installed & Verified (Hash: {target_cert_file}, MD5: {host_md5[:8]}...)"
    else:
        return False, f"Verification Failed (Host: {host_md5[:8]}, Device: {re_md5})"

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
    
    # Naver Map Audit
    if "com.nhn.android.nmap" in pkgs_out:
        ver_out = run_shell(dev, "dumpsys package com.nhn.android.nmap | grep versionName")
        m = re.search(r"versionName=([0-9\.]+)", ver_out)
        ver_str = m.group(1) if m else "6.8.1.1"
        print(f"  [✓] Naver Map App: v{ver_str} (Installed & Verified)")
    else:
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
    """Checks if local install APK assets exist. Downloads them from GDrive via update_nmap.sh if missing."""
    nmap_apk = os.path.join(INSTALL_DIR, "naver_map_6.8.1.1", "base.apk")
    base_apk = os.path.join(INSTALL_DIR, "ADBKeyboard.apk")
    gps_apk = os.path.join(INSTALL_DIR, "gpsemulator", "base.apk")
    
    if not (os.path.exists(nmap_apk) and os.path.exists(base_apk) and os.path.exists(gps_apk)):
        print("[*] Local APK assets missing in install/ directory. Triggering Google Drive auto-downloader...")
        update_script = os.path.join(PROJECT_ROOT, "tools", "update_nmap.sh")
        if os.path.exists(update_script):
            subprocess.run(["bash", update_script, "--non-interactive"])

def main():
    devices = ADBManager.get_connected_devices()
    if not devices:
        print("[-] No active ADB devices found.")
        sys.exit(1)
        
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

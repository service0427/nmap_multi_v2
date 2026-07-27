#!/usr/bin/env python3
# Nmap Multi V2: First-run device initialization and environment validation pipeline
import sys
import os
import time
import subprocess

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src", "lib"))
from adb import ADBManager

def run_cmd(device_id, cmd_str):
    out, err, rc = ADBManager.run_adb(device_id, f"shell \"{cmd_str}\"")
    return out.strip()

def verify_and_install_mitm_cert(dev):
    """Verifies host PC mitmproxy CA certificate against device CA store and installs if missing/mismatched."""
    cert_path = os.path.expanduser("~/.mitmproxy/mitmproxy-ca-cert.pem")
    if not os.path.exists(cert_path):
        # Trigger mitmproxy cert generation if missing on host
        subprocess.run("mitmdump --help >/dev/null 2>&1", shell=True)
        time.sleep(1)
        
    if not os.path.exists(cert_path):
        return False, "Host mitmproxy cert (~/.mitmproxy/mitmproxy-ca-cert.pem) missing"

    # 1. Compute subject hash (old format)
    try:
        res = subprocess.run(["openssl", "x509", "-inform", "PEM", "-subject_hash_old", "-in", cert_path], capture_output=True, text=True, check=True)
        cert_hash = res.stdout.strip().splitlines()[0]
    except Exception as e:
        return False, f"Failed to compute cert hash: {e}"

    # 2. Compute host cert MD5 sum
    try:
        res = subprocess.run(["md5sum", cert_path], capture_output=True, text=True, check=True)
        host_md5 = res.stdout.split()[0]
    except Exception as e:
        return False, f"Failed to compute host cert MD5: {e}"

    target_cert_file = f"{cert_hash}.0"
    user_cert_path = f"/data/misc/user/0/cacerts-added/{target_cert_file}"
    magisk_cert_path = f"/data/adb/modules/trustusercerts/system/etc/security/cacerts/{target_cert_file}"

    # 3. Query device certificate MD5 sum
    dev_md5_out, _, _ = ADBManager.run_adb(dev, f"shell \"su -c 'md5sum {user_cert_path} 2>/dev/null || md5sum {magisk_cert_path} 2>/dev/null'\"")
    dev_md5 = dev_md5_out.strip().split()[0] if dev_md5_out else None

    if dev_md5 == host_md5:
        return True, f"Verified & Active (Hash: {target_cert_file}, MD5: {host_md5[:8]}...)"

    # 4. Push and install host cert to device
    ADBManager.run_adb(dev, f"push {cert_path} /data/local/tmp/{target_cert_file}")
    
    install_cmd = (
        f"mkdir -p /data/misc/user/0/cacerts-added && "
        f"cp /data/local/tmp/{target_cert_file} {user_cert_path} && "
        f"chown 1000:1000 {user_cert_path} && chmod 644 {user_cert_path} && "
        f"mkdir -p /data/adb/modules/trustusercerts/system/etc/security/cacerts 2>/dev/null || true && "
        f"cp /data/local/tmp/{target_cert_file} {magisk_cert_path} 2>/dev/null || true && "
        f"chmod 644 {magisk_cert_path} 2>/dev/null || true && "
        f"rm -f /data/local/tmp/{target_cert_file}"
    )
    ADBManager.run_adb(dev, f"shell \"su -c '{install_cmd}'\"")
    
    # 5. Re-verify MD5 sum on device
    re_out, _, _ = ADBManager.run_adb(dev, f"shell \"su -c 'md5sum {user_cert_path} 2>/dev/null || md5sum {magisk_cert_path} 2>/dev/null'\"")
    re_md5 = re_out.strip().split()[0] if re_out else None
    
    if re_md5 == host_md5:
        return True, f"Installed & Verified (Hash: {target_cert_file}, MD5: {host_md5[:8]}...)"
    else:
        return False, f"Verification Failed (Host: {host_md5[:8]}, Device: {re_md5})"

def init_single_device(dev):
    print(f"[*] Initializing device {dev}...")
    
    # 1. Root & System Settings
    run_cmd(dev, "su 0 settings put global bluetooth_on 0")
    run_cmd(dev, "su 0 settings put system volume_music 0")
    run_cmd(dev, "su 0 settings put system volume_notification 0")
    run_cmd(dev, "su 0 settings put system volume_ring 0")
    run_cmd(dev, "su 0 settings put system volume_system 0")
    run_cmd(dev, "su 0 settings put global captive_portal_mode 0")
    run_cmd(dev, "su 0 settings put global captive_portal_detection_enabled 0")
    run_cmd(dev, "su 0 settings put system accelerometer_rotation 0")
    run_cmd(dev, "su 0 settings put system user_rotation 0") # Portrait orientation
    
    # 2. Disaster alert & location scan toggles
    run_cmd(dev, "su 0 settings put global wifi_scan_always_enabled 0")
    run_cmd(dev, "su 0 settings put global ble_scan_always_enabled 0")
    
    # 3. Grant Permissions for Naver Map
    pkg = "com.nhn.android.nmap"
    permissions = [
        "android.permission.ACCESS_FINE_LOCATION",
        "android.permission.ACCESS_COARSE_LOCATION",
        "android.permission.ACCESS_BACKGROUND_LOCATION",
        "android.permission.READ_PHONE_STATE",
        "android.permission.WRITE_EXTERNAL_STORAGE",
        "android.permission.READ_EXTERNAL_STORAGE"
    ]
    for perm in permissions:
        run_cmd(dev, f"su 0 pm grant {pkg} {perm} 2>/dev/null")
        
    # 4. Check if ZFlip is folded and force OPEN state (state 3)
    ADBManager.check_and_fix_zflip(dev)

    # 5. MITM CA Certificate Validation & Installation
    cert_ok, cert_msg = verify_and_install_mitm_cert(dev)
    status_icon = "✓" if cert_ok else "⚠️"
    print(f"  [{status_icon}] MITM CA Cert: {cert_msg}")
    print(f"  [✓] Device {dev} basic settings initialized.")

def main():
    devices = ADBManager.get_connected_devices()
    if not devices:
        print("[-] No active ADB devices found.")
        sys.exit(1)
        
    print(f"============================================================")
    print(f"🚀 Nmap Multi V2: Device Initialization Pipeline ({len(devices)} devices)")
    print(f"============================================================")
    
    for dev in devices:
        init_single_device(dev)
            
    print("============================================================")
    print("[✓] All connected devices initialized successfully.")

if __name__ == "__main__":
    main()

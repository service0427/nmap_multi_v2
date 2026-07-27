#!/usr/bin/env python3
import socket
import re
import subprocess
import json
import xml.etree.ElementTree as ET
import urllib.request
import urllib.error
import sys
import time
import os

V2_ROOT = "/home/tech/nmap_multi_v2"
sys.path.insert(0, os.path.join(V2_ROOT, "src", "lib"))
import api_client

def get_lte_interfaces():
    interfaces = []
    try:
        output = subprocess.check_output(["ip", "-br", "addr", "show"]).decode()
        for line in output.splitlines():
            parts = line.split()
            if not parts: continue
            name = parts[0]
            match = re.match(r'^lte(\d+)$', name)
            if match:
                subnet = int(match.group(1))
                interfaces.append((name, subnet))
    except Exception as e:
        print(f"Error listing interfaces: {e}")
    return sorted(interfaces)

def get_interface_ip(interface):
    try:
        output = subprocess.check_output(f"ip -4 addr show {interface}", shell=True).decode()
        match = re.search(r'inet\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', output)
        if match:
            return match.group(1)
    except: pass
    return "0.0.0.0"

def get_modem_traffic(subnet):
    modem_ip = f"192.168.{subnet}.1"
    sestok_url = f"http://{modem_ip}/api/webserver/SesTokInfo"
    try:
        req = urllib.request.Request(sestok_url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as response:
            xml_data = response.read()
            root = ET.fromstring(xml_data)
            ses_info = root.findtext("SesInfo")
            tok_info = root.findtext("TokInfo")
    except: return None
        
    if not ses_info or not tok_info: return None
        
    stats_url = f"http://{modem_ip}/api/monitoring/traffic-statistics"
    try:
        headers = {
            "Cookie": f"SessionID={ses_info}",
            "__RequestVerificationToken": tok_info
        }
        req = urllib.request.Request(stats_url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=5) as response:
            xml_data = response.read()
            root = ET.fromstring(xml_data)
            total_upload = root.findtext("TotalUpload")
            total_download = root.findtext("TotalDownload")
            return {
                "upload": int(total_upload) if total_upload else 0,
                "download": int(total_download) if total_download else 0
            }
    except: return None

# API usage stats calls are managed via api_client module

failure_counts = {}

def get_usb_port(interface):
    try:
        dev_path = os.path.realpath(f"/sys/class/net/{interface}/device")
        parts = dev_path.split('/')
        for part in reversed(parts):
            if re.match(r'^\d+-\d+(\.\d+)*$', part):
                return part
    except Exception as e:
        print(f"[RECOVERY] Error getting USB port for {interface}: {e}")
    return None

def recover_modem(interface):
    print(f"[RECOVERY] 🚨 {interface} failed consecutively! Attempting self-healing...")
    usb_port = get_usb_port(interface)
    if not usb_port:
        print(f"[RECOVERY] USB port not found. Skipping reset.")
        return
        
    print(f"[RECOVERY] Target USB port: {usb_port}. unbind/bind reset...")
    subprocess.run(f"echo '{usb_port}' | sudo tee /sys/bus/usb/drivers/usb/unbind", shell=True, stdout=subprocess.DEVNULL)
    time.sleep(3)
    res = subprocess.run(f"echo '{usb_port}' | sudo tee /sys/bus/usb/drivers/usb/bind", shell=True, capture_output=True, text=True)
    
    if res.returncode != 0 or "No such device" in res.stderr:
        print(f"[RECOVERY] ⚠️ Single port bind failed. PCI Host Controller level reset...")
        try:
            dev_path = os.path.realpath(f"/sys/class/net/{interface}/device")
            pci_match = re.search(r'0000:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-9a-fA-F]', dev_path)
            if pci_match:
                pci_addr = pci_match.group(0)
                subprocess.run(f"echo '{pci_addr}' | sudo tee /sys/bus/pci/drivers/xhci_hcd/unbind", shell=True, stdout=subprocess.DEVNULL)
                time.sleep(3)
                subprocess.run(f"echo '{pci_addr}' | sudo tee /sys/bus/pci/drivers/xhci_hcd/bind", shell=True, stdout=subprocess.DEVNULL)
                time.sleep(5)
                subprocess.run(["sudo", "udevadm", "trigger"])
                time.sleep(8)
        except Exception as e:
            print(f"[RECOVERY] Fallback PCI reset failed: {e}")
    else:
        time.sleep(5)
        
    print(f"[RECOVERY] Running lte-sync to restore routing...")
    for attempt in range(3):
        time.sleep(5)
        try:
            subprocess.run(["sudo", "/usr/local/bin/lte-sync"], timeout=30)
        except Exception as e:
            print(f"[RECOVERY] Failed to run lte-sync: {e}")

def run_once():
    hostname = socket.gethostname()
    interfaces = get_lte_interfaces()
    print(f"=== Sending LTE usage to {api_client.API_SERVER} ===")
    
    for name, subnet in interfaces:
        stats = get_modem_traffic(subnet)
        if stats:
            failure_counts[name] = 0
            upload_raw = stats["upload"]
            download_raw = stats["download"]
            combined_name = f"{hostname}_{name}"
            ip_addr = get_interface_ip(name)
            
            success, message = api_client.send_lte_usage(combined_name, upload_raw, download_raw, ip_addr)
            status_str = "SUCCESS" if success else "FAILED"
            print(f"[{status_str}] {combined_name} ({ip_addr}) -> Upload: {upload_raw} Bytes, Download: {download_raw} Bytes | Response: {message}")
        else:
            failure_counts[name] = failure_counts.get(name, 0) + 1
            cur_fails = failure_counts[name]
            print(f"[ERROR] {name} -> Could not fetch traffic data | Consec Fails: {cur_fails}/10")
            if cur_fails >= 10:
                failure_counts[name] = 0
                recover_modem(name)

def main():
    daemon_mode = "--daemon" in sys.argv or "-d" in sys.argv
    if daemon_mode:
        print(f"Starting LTE Usage Sender in daemon mode...")
        while True:
            try:
                run_once()
            except Exception as e:
                print(f"Error: {e}")
            time.sleep(60)
    else:
        run_once()

if __name__ == "__main__":
    main()

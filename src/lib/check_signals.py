#!/usr/bin/env python3
import os
import sys
import subprocess
import re
from datetime import datetime

# Attempt to import huawei_lte_api, fallback gracefully
try:
    from huawei_lte_api.Client import Client
    from huawei_lte_api.Connection import Connection
    HUAWEI_API_AVAILABLE = True
except ImportError:
    HUAWEI_API_AVAILABLE = False

USERNAME = "admin"
PASSWORD = "KdjLch!@7024"
TIMEOUT = 3

# ANSI Colors
RESET = "\033[0m"
BOLD = "\033[1m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"

def get_current_ip(modem_name):
    # Resolve exact assigned IPv4 for PBR routing lookup
    bind_target = modem_name
    try:
        res = subprocess.run(f"ip -4 addr show dev {modem_name} | grep -oP 'inet \\K[0-9.]+'",
                             shell=True, capture_output=True, text=True, timeout=2)
        dev_ip = res.stdout.strip()
        if dev_ip:
            bind_target = dev_ip
    except:
        pass

    test_urls = ["http://ifconfig.me", "http://api.ipify.org", "http://icanhazip.com"]
    for url in test_urls:
        try:
            result = subprocess.run(f"curl --interface {bind_target} -s -m 4 {url}",
                                  shell=True, capture_output=True, text=True, timeout=5)
            ip = result.stdout.strip()
            if ip and ip.split('.')[0].isdigit():
                return ip
        except:
            continue
    return "OFFLINE"

def get_rsrp_info(rsrp):
    if rsrp is None:
        return RESET, "미측정"
    if rsrp >= -80:
        return GREEN, "최상"
    elif rsrp >= -90:
        return CYAN, "좋음"
    elif rsrp >= -100:
        return YELLOW, "보통"
    else:
        return RED, "불량"

def get_sinr_info(sinr):
    if sinr is None:
        return RESET, "미측정"
    if sinr >= 10.0:
        return GREEN, "최상"
    elif sinr >= 3.0:
        return CYAN, "좋음"
    elif sinr >= 0.0:
        return YELLOW, "보통"
    else:
        return RED, "불량"

def parse_signal_value(value):
    if value is None or value == 'None':
        return None
    try:
        if isinstance(value, str):
            value = value.replace('dBm', '').replace('dB', '').strip()
        return float(value)
    except:
        return None

def main():
    print("=========================================================================================================")
    print(f"📡 LTE Modem Signal & Connection Diagnostics (Checked at: {datetime.now().strftime('%H:%M:%S')})")
    print("=========================================================================================================")
    print(f"{BOLD}{'Modem':<6} | {'Status':<8} | {'External IP':<15} | {'RSRP (신호감도)':<14} | {'RSRQ':<5} | {'RSSI':<5} | {'SINR (신호품질)':<14} | {'Band':<4} | {'PCI':<4} | {'Cell ID':<10}{RESET}")
    print("---------------------------------------------------------------------------------------------------------")

    # Dynamically scan for active lte* interfaces
    lte_interfaces = []
    try:
        for name in os.listdir('/sys/class/net'):
            if name.startswith("lte"):
                lte_interfaces.append(name)
    except:
        pass
    
    def extract_num(s):
        m = re.search(r'\d+', s)
        return int(m.group(0)) if m else 0
    
    lte_interfaces = sorted(list(set(lte_interfaces)), key=extract_num)
    if not lte_interfaces:
        # Fallback defaults if none detected (lte11 ~ lte20)
        lte_interfaces = [f"lte{i}" for i in range(11, 21)]

    for modem_name in lte_interfaces:
        subnet_match = re.search(r'\d+', modem_name)
        subnet = subnet_match.group(0) if subnet_match else "11"
        modem_ip = f"192.168.{subnet}.1"
        
        # Test physical interface check
        if not os.path.exists(f"/sys/class/net/{modem_name}"):
            print(f"{RED}{modem_name:<6} | {'MISSING':<8} | {'N/A':<15} | {'N/A':<14} | {'N/A':<5} | {'N/A':<5} | {'N/A':<14} | {'N/A':<4} | {'N/A':<4} | {'N/A':<10}{RESET}")
            continue

        # Check connection status
        ip_addr = get_current_ip(modem_name)
        status_str = f"{GREEN}ONLINE{RESET}" if ip_addr != "OFFLINE" else f"{RED}OFFLINE{RESET}"

        # Connect to Huawei API
        rsrp_val = None
        rsrq_val = None
        rssi_val = None
        sinr_val = None
        band = "N/A"
        pci = "N/A"
        cell_id = "N/A"
        
        if HUAWEI_API_AVAILABLE:
            try:
                connection = Connection(f'http://{modem_ip}/', username=USERNAME, password=PASSWORD, timeout=TIMEOUT)
                client = Client(connection)
                signal = client.device.signal()
                
                rsrp_val = parse_signal_value(signal.get('rsrp'))
                rsrq_val = parse_signal_value(signal.get('rsrq'))
                rssi_val = parse_signal_value(signal.get('rssi'))
                sinr_val = parse_signal_value(signal.get('sinr'))
                
                band = signal.get('band', 'N/A')
                pci = signal.get('pci', 'N/A')
                cell_id = signal.get('cell_id', 'N/A')
                
                try:
                    client.user.logout()
                except: pass
            except Exception as e:
                pass

        # Determine color and evaluation text
        rsrp_color, rsrp_eval = get_rsrp_info(rsrp_val)
        sinr_color, sinr_eval = get_sinr_info(sinr_val)

        # Build output strings with evaluation
        rsrp_str = f"{rsrp_val:.0f}dBm({rsrp_eval})" if rsrp_val is not None else "N/A"
        rsrq_str = f"{rsrq_val:.0f}dB" if rsrq_val is not None else "N/A"
        rssi_str = f"{rssi_val:.0f}dBm" if rssi_val is not None else "N/A"
        sinr_str = f"{sinr_val:.1f}dB({sinr_eval})" if sinr_val is not None else "N/A"

        # Print row
        print(f"{BOLD}{modem_name:<6}{RESET} | {status_str:<17} | {ip_addr:<15} | "
              f"{rsrp_color}{rsrp_str:<14}{RESET} | {rsrq_str:<5} | {rssi_str:<5} | "
              f"{sinr_color}{sinr_str:<14}{RESET} | {band:<4} | {pci:<4} | {cell_id:<10}")

    print("=========================================================================================================")
    print(f"{BOLD}신호 상태 가이드 (RSRP / SINR):{RESET}")
    print(f" - {GREEN}최상 (GREEN){RESET}  : 모뎀 통신 상태가 완벽하며 데이터 유실이 없습니다.")
    print(f" - {CYAN}좋음 (CYAN){RESET}   : 매우 우수한 상태로 안정적인 가동이 가능합니다.")
    print(f" - {YELLOW}보통 (YELLOW){RESET} : 약간의 신호 감쇠가 존재하며 가끔 일시적인 패킷 유실이 발생할 수 있습니다.")
    print(f" - {RED}불량 (RED){RESET}    : 신호가 극히 약하거나 간섭이 심하여 캡차 타임아웃 및 인터넷 먹통의 원인이 됩니다.")
    print("=========================================================================================================")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import os
import sys
import time
import re
from datetime import datetime

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

def format_rate(rate_bytes_sec):
    try:
        rate = float(rate_bytes_sec)
        rate_bits = rate * 8
        if rate < 1024:
            return f"{rate:.0f} B/s"
        elif rate < 1024 * 1024:
            return f"{rate / 1024:.1f} KB/s ({rate_bits / 1000 / 1000:.2f} Mbps)"
        else:
            return f"{rate / 1024 / 1024:.2f} MB/s ({rate_bits / 1000 / 1000:.1f} Mbps)"
    except:
        return "N/A"

def format_bytes(bytes_val):
    try:
        b = float(bytes_val)
        if b < 1024 * 1024:
            return f"{b / 1024:.1f} KB"
        elif b < 1024 * 1024 * 1024:
            return f"{b / 1024 / 1024:.1f} MB"
        else:
            return f"{b / 1024 / 1024 / 1024:.2f} GB"
    except:
        return "N/A"

def format_time(seconds_str):
    try:
        sec = int(seconds_str)
        hours = sec // 3600
        minutes = (sec % 3600) // 60
        seconds = sec % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    except:
        return "N/A"

def query_modem_traffic(subnet):
    modem_ip = f"192.168.{subnet}.1"
    if not HUAWEI_API_AVAILABLE:
        return None
    try:
        connection = Connection(f'http://{modem_ip}/', username=USERNAME, password=PASSWORD, timeout=TIMEOUT)
        client = Client(connection)
        stats = client.monitoring.traffic_statistics()
        try:
            client.user.logout()
        except: pass
        return stats
    except Exception:
        return None

def draw_dashboard():
    if len(sys.argv) > 1 and sys.argv[1] in ("-w", "--watch"):
        print("\033[H\033[J", end="")

    print("==================================================================================================================")
    print(f"📊 LTE Modem Real-Time Traffic & Speed Dashboard (Checked at: {datetime.now().strftime('%H:%M:%S')})")
    print("==================================================================================================================")
    print(f"{BOLD}{'Modem':<6} | {'Status':<7} | {'Uptime':<8} | {'Upload Speed':<24} | {'Download Speed':<24} | {'Sent Data':<10} | {'Recv Data':<10}{RESET}")
    print("------------------------------------------------------------------------------------------------------------------")

    # Dynamically scan active lte interfaces
    lte_ifaces = []
    try:
        for iface in os.listdir('/sys/class/net'):
            if iface.startswith('lte'):
                lte_ifaces.append(iface)
    except: pass
    
    def extract_num(s):
        m = re.search(r'\d+', s)
        return int(m.group(0)) if m else 0
    
    lte_ifaces = sorted(list(set(lte_ifaces)), key=extract_num)
    if not lte_ifaces:
        lte_ifaces = [f"lte{i}" for i in range(11, 21)]

    for modem_name in lte_ifaces:
        m_num = re.search(r'\d+', modem_name)
        subnet = m_num.group(0) if m_num else "11"
        
        if not os.path.exists(f"/sys/class/net/{modem_name}"):
            print(f"{RED}{modem_name:<6} | {'MISSING':<7} | {'N/A':<8} | {'N/A':<24} | {'N/A':<24} | {'N/A':<10} | {'N/A':<10}{RESET}")
            continue

        stats = query_modem_traffic(subnet)
        if stats is None:
            print(f"{RED}{modem_name:<6} | {'OFFLINE':<7} | {'N/A':<8} | {'N/A':<24} | {'N/A':<24} | {'N/A':<10} | {'N/A':<10}{RESET}")
            continue

        uptime = format_time(stats.get('CurrentConnectTime'))
        up_speed = format_rate(stats.get('CurrentUploadRate', 0))
        down_speed = format_rate(stats.get('CurrentDownloadRate', 0))
        sent = format_bytes(stats.get('CurrentUpload', 0))
        recv = format_bytes(stats.get('CurrentDownload', 0))

        print(f"{BOLD}{modem_name:<6}{RESET} | {GREEN}{'ONLINE':<7}{RESET} | {uptime:<8} | {up_speed:<24} | {down_speed:<24} | {sent:<10} | {recv:<10}")

    print("==================================================================================================================")

def main():
    watch_mode = len(sys.argv) > 1 and sys.argv[1] in ("-w", "--watch")
    if watch_mode:
        try:
            while True:
                draw_dashboard()
                time.sleep(2)
        except KeyboardInterrupt:
            pass
    else:
        draw_dashboard()

if __name__ == "__main__":
    main()

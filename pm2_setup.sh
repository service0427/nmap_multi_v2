#!/usr/bin/env bash
# pm2_setup.sh: Register Nmap Multi V2 services to PM2
# Multi-Node & Mini PC Deployment Compatible

PROJECT_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$PROJECT_ROOT" || exit 1

echo "============================================================"
echo "   Nmap Multi V2 Production Service Registration (PM2)"
echo "   Root: $PROJECT_ROOT"
echo "============================================================"

# Ensure PM2 is installed
if ! command -v pm2 >/dev/null 2>&1; then
    echo "[*] PM2 not found. Installing..."
    sudo npm install -g pm2
fi

# 1. Register Web Monitor (Port 5000)
if [ -f "tools/scrcpy/sync_gui_control.py" ]; then
    echo "[*] Registering Nmap Web Monitor (Port 5000)..."
    pm2 delete nmap-monitor 2>/dev/null
    pm2 start tools/scrcpy/sync_gui_control.py --name "nmap-monitor" --interpreter python3
else
    echo "[!] tools/scrcpy/sync_gui_control.py not found. Skipping."
fi

# 2. Register Schedulers (ALL STOPPED BY DEFAULT - User selects active mode)
if [ -f "start.sh" ]; then
    echo "[*] Registering Nmap Schedulers for all operational modes (STOPPED state)..."
    chmod +x start.sh
    
    # 2.1 Mini PC / Local WAN Mode (Public Wi-Fi / Single PC IP)
    pm2 delete nmap-scheduler-local 2>/dev/null
    pm2 start ./start.sh --name "nmap-scheduler-local" -- --mode local
    pm2 stop nmap-scheduler-local
    
    # 2.2 Central Multi-LTE Modem PBR Mode (lte11 ~ lteXX)
    pm2 delete nmap-scheduler-eth 2>/dev/null
    pm2 start ./start.sh --name "nmap-scheduler-eth" -- --mode eth
    pm2 stop nmap-scheduler-eth

    # 2.3 Multi-Wi-Fi Gateway Mode
    pm2 delete nmap-scheduler-wifi 2>/dev/null
    pm2 start ./start.sh --name "nmap-scheduler-wifi" -- --mode wifi
    pm2 stop nmap-scheduler-wifi

    # Default Alias (nmap-scheduler -> local)
    pm2 delete nmap-scheduler 2>/dev/null
    pm2 start ./start.sh --name "nmap-scheduler" -- --mode local
    pm2 stop nmap-scheduler
else
    echo "[!] start.sh not found. Skipping."
fi

# 3. Register Log Cleaner (Hourly Cron)
if [ -f "tools/clean_logs.sh" ]; then
    echo "[*] Registering Nmap Log Cleaner (Hourly Cron)..."
    chmod +x tools/clean_logs.sh
    pm2 delete nmap-log-cleaner 2>/dev/null
    pm2 start tools/clean_logs.sh --name "nmap-log-cleaner" --cron "0 * * * *" --no-autorestart
else
    echo "[!] tools/clean_logs.sh not found. Skipping."
fi

# 4. Register ADB Recovery Monitor (Daemon)
if [ -f "tools/adb_recovery_monitor.py" ]; then
    echo "[*] Registering ADB Recovery Monitor..."
    chmod +x tools/adb_recovery_monitor.py
    pm2 delete adb-recovery-monitor 2>/dev/null
    pm2 start tools/adb_recovery_monitor.py --name "adb-recovery-monitor" --interpreter python3
else
    echo "[!] tools/adb_recovery_monitor.py not found. Skipping."
fi

# 5. Register LTE Usage Sender (Daemon - optional for eth mode)
if [ -f "tools/sync_modems.py" ]; then
    echo "[*] Registering Nmap LTE Usage Sender (Daemon)..."
    chmod +x tools/sync_modems.py
    pm2 delete lte-usage-sender 2>/dev/null
    pm2 start tools/sync_modems.py --name "lte-usage-sender" --interpreter python3 -- --daemon
    pm2 stop lte-usage-sender
else
    echo "[!] tools/sync_modems.py not found. Skipping."
fi

# 6. Register Dev Control API (Port 5555) & Web Dashboard (Port 5001)
if [ -f "dev_control/api/server.py" ]; then
    echo "[*] Registering Dev Control API (Port 5555)..."
    pm2 delete nmap-dev-api 2>/dev/null
    pm2 start dev_control/api/server.py --name "nmap-dev-api" --interpreter python3
fi

if [ -f "dev_control/web/app.py" ]; then
    echo "[*] Registering Dev Control Web (Port 5001)..."
    pm2 delete nmap-dev-web 2>/dev/null
    pm2 start dev_control/web/app.py --name "nmap-dev-web" --interpreter python3
fi

# Save PM2 configuration
pm2 save
echo "============================================================"
echo "   PM2 Multi-Node Setup Complete!"
echo "   To start Mini PC local mode: pm2 start nmap-scheduler-local"
echo "   To start LTE modem eth mode:  pm2 start nmap-scheduler-eth"
echo "============================================================"

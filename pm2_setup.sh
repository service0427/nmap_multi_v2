#!/usr/bin/env bash
# pm2_setup.sh: Register Nmap Multi V2 services to PM2

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

# 1. Register Web Monitor
if [ -f "tools/scrcpy/sync_gui_control.py" ]; then
    echo "[*] Registering Nmap Web Monitor (Port 5000)..."
    pm2 delete nmap-monitor 2>/dev/null
    pm2 start tools/scrcpy/sync_gui_control.py --name "nmap-monitor" --interpreter python3
else
    echo "[!] tools/scrcpy/sync_gui_control.py not found. Skipping."
fi

# 2. Register Scheduler (STOPPED by default)
if [ -f "start.sh" ]; then
    echo "[*] Registering Nmap Scheduler (STOPPED state)..."
    chmod +x start.sh
    pm2 delete nmap-scheduler 2>/dev/null
    pm2 start ./start.sh --name "nmap-scheduler" -- --mode eth
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

# 3.5 Register ADB Recovery Monitor (Daemon)
if [ -f "tools/adb_recovery_monitor.py" ]; then
    echo "[*] Registering ADB Recovery Monitor..."
    chmod +x tools/adb_recovery_monitor.py
    pm2 delete adb-recovery-monitor 2>/dev/null
    pm2 start tools/adb_recovery_monitor.py --name "adb-recovery-monitor" --interpreter python3
else
    echo "[!] tools/adb_recovery_monitor.py not found. Skipping."
fi

# 3.6 Register LTE Usage Sender (Daemon)
if [ -f "tools/sync_modems.py" ]; then
    echo "[*] Registering Nmap LTE Usage Sender (Daemon)..."
    chmod +x tools/sync_modems.py
    pm2 delete lte-usage-sender 2>/dev/null
    pm2 start tools/sync_modems.py --name "lte-usage-sender" --interpreter python3 -- --daemon
else
    echo "[!] tools/sync_modems.py not found. Skipping."
fi


# 3.7 Register LTE IP Rotator (Daemon)
if [ -f "tools/lte_ip_rotator.py" ]; then
    echo "[*] Registering LTE IP Rotator (Daemon)..."
    chmod +x tools/lte_ip_rotator.py
    pm2 delete lte-ip-rotator 2>/dev/null
    pm2 start tools/lte_ip_rotator.py --name "lte-ip-rotator" --interpreter python3
else
    echo "[!] tools/lte_ip_rotator.py not found. Skipping."
fi

# 3.8 Register Dev Control API (Port 5555) & Web Dashboard (Port 5001)
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

# 4. Save PM2 configuration
pm2 save
echo "============================================================"
echo "   PM2 Setup for Nmap Multi V2 Complete!"
echo "============================================================"

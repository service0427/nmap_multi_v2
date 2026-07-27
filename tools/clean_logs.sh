#!/usr/bin/env bash
# tools/clean_logs.sh: Robust Hourly log cleanup with Dynamic Disk Usage Safety

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
LOG_ROOT="/home/tech/nmap_multi_v2/logs"
NOW=$(date +"%Y-%m-%d %H:%M:%S")

echo "[$NOW] Starting Dynamic Hourly Cleanup for nmap_multi_v2..."

if [ ! -d "$LOG_ROOT" ]; then
    echo "[$NOW] [!] Log root not found: $LOG_ROOT"
    exit 1
fi

# 1. Get current root disk usage percentage
DISK_USAGE=$(df / | tail -1 | awk '{print $5}' | sed 's/%//')

# 2. Determine retention limit based on disk usage
if [ "$DISK_USAGE" -ge 90 ]; then
    KEEP_TIME="2 hours ago"
elif [ "$DISK_USAGE" -ge 80 ]; then
    KEEP_TIME="2 hours ago"
elif [ "$DISK_USAGE" -ge 70 ]; then
    KEEP_TIME="4 hours ago"
elif [ "$DISK_USAGE" -ge 50 ]; then
    KEEP_TIME="8 hours ago"
else
    KEEP_TIME="24 hours ago"
fi

echo "[$NOW] Current Disk Usage: $DISK_USAGE%. Setting retention threshold to: $KEEP_TIME"

# 3. Delete files older than threshold at depth 2 or deeper
find "$LOG_ROOT" -mindepth 2 -type f -not -newermt "$KEEP_TIME" \
    ! -path "*/tmp*" \
    ! -path "*/locks*" \
    ! -path "*/stealth_logs*" \
    ! -path "*/rotator_history*" \
    ! -name "current_task.json" \
    ! -name "nmap_lock" \
    -delete 2>/dev/null

# 4. Specific 30-day retention cleanup for stealth_logs and rotator_history
if [ -d "$LOG_ROOT/stealth_logs" ]; then
    find "$LOG_ROOT/stealth_logs" -type f -mtime +30 -delete 2>/dev/null
fi
if [ -d "$LOG_ROOT/rotator_history" ]; then
    find "$LOG_ROOT/rotator_history" -type f -mtime +30 -delete 2>/dev/null
fi

# 5. Cleanup empty directories (date folders, session folders)
find "$LOG_ROOT" -mindepth 2 -type d -empty -delete 2>/dev/null

echo "[$NOW] Cleanup complete. Disk usage remains at $DISK_USAGE%."

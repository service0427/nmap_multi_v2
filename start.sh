#!/usr/bin/env bash
# Nmap Multi V2: Main entry scheduler and diagnostics wrapper

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR" || exit 1

print_help() {
    echo "Nmap Multi: Unified Runner CLI"
    echo "Usage:"
    echo "  ./start.sh --mode eth          Launch scheduler in LTE PBR mode (foreground)"
    echo "  ./start.sh --mode local        Launch scheduler in Local wired WAN mode (foreground)"
    echo "  ./start.sh --mode wifi         Launch scheduler in Wi-Fi multi-gateway mode (foreground)"
    echo "  ./start.sh --signals           Show LTE modem signals diagnostic table"
    echo "  ./start.sh --gui               Launch scrcpy multi-device sync control mirror"
    exit 0
}

if [ $# -lt 1 ]; then
    print_help
fi

case "$1" in
    --mode)
        MODE="$2"
        if [ "$MODE" != "eth" ] && [ "$MODE" != "local" ] && [ "$MODE" != "wifi" ]; then
            echo "[-] Error: Invalid mode '$MODE'. Must be 'eth', 'local', or 'wifi'."
            exit 1
        fi
        echo "[*] Launching Nmap Multi Scheduler in '$MODE' mode..."
        exec python3 src/core/scheduler.py --mode "$MODE"
        ;;
    --signals)
        exec python3 src/lib/check_signals.py
        ;;
    --gui)
        if [ -f "tools/scrcpy/sync_gui_control.py" ]; then
            exec python3 tools/scrcpy/sync_gui_control.py
        else
            echo "[-] Error: GUI control script not found."
            exit 1
        fi
        ;;
    *)
        print_help
        ;;
esac

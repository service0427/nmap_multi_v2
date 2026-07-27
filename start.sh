#!/usr/bin/env bash
# Nmap Multi V2: Main Entry Scheduler and CLI Controller Wrapper

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR" || exit 1

print_help() {
    echo "============================================================"
    echo "⚡ Nmap Multi V2: Unified Management CLI"
    echo "============================================================"
    echo "Usage:"
    echo "  ./start.sh --mode <eth|local|wifi>     Launch Parallel Async Scheduler (default)"
    echo "  ./start.sh --legacy-mode <mode>        Launch Legacy Single-Thread Scheduler"
    echo "  ./start.sh --device <ID> --action <A>  Perform targeted device action"
    echo "  ./start.sh --signals                   Display LTE Modem Signal Diagnostics"
    echo "  ./start.sh --gui                       Launch Scrcpy Multi-Device Sync Mirror"
    echo "  ./start.sh --help                      Show this help message"
    echo ""
    echo "Supported Actions (--action):"
    echo "  restart, stop, pause, start, mute, clear_cooldown"
    echo ""
    echo "Examples:"
    echo "  ./start.sh --mode eth"
    echo "  ./start.sh --device R5CR80ZNCXT --action restart"
    echo "  ./start.sh --device R3CR70AV5ZZ --action mute"
    echo "============================================================"
    exit 0
}

if [ $# -lt 1 ]; then
    print_help
fi

DEVICE_ID=""
ACTION_CMD=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode)
            MODE="$2"
            shift 2
            if [ "$MODE" != "eth" ] && [ "$MODE" != "local" ] && [ "$MODE" != "wifi" ]; then
                echo "[-] Error: Invalid mode '$MODE'. Must be 'eth', 'local', or 'wifi'."
                exit 1
            fi
            echo "[*] Launching Nmap Multi Async Parallel Scheduler in '$MODE' mode..."
            exec python3 src/core/scheduler_async.py --mode "$MODE"
            ;;
        --legacy-mode)
            MODE="$2"
            shift 2
            if [ "$MODE" != "eth" ] && [ "$MODE" != "local" ] && [ "$MODE" != "wifi" ]; then
                echo "[-] Error: Invalid mode '$MODE'. Must be 'eth', 'local', or 'wifi'."
                exit 1
            fi
            echo "[*] Launching Legacy Single-Thread Scheduler in '$MODE' mode..."
            exec python3 src/core/scheduler.py --mode "$MODE"
            ;;
        --device)
            DEVICE_ID="$2"
            shift 2
            ;;
        --action)
            ACTION_CMD="$2"
            shift 2
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
        -h|--help)
            print_help
            ;;
        *)
            echo "[-] Error: Unknown argument '$1'"
            print_help
            ;;
    esac
done

if [ -n "$DEVICE_ID" ] && [ -n "$ACTION_CMD" ]; then
    exec python3 dev_control/cli.py --device "$DEVICE_ID" --action "$ACTION_CMD"
else
    print_help
fi

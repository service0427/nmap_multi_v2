#!/usr/bin/env bash
# tools/balance_modem_devices.sh: Rebuild the unified devices_manifest.json

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
exec python3 "$SCRIPT_DIR/map_usb_ports.py" "$@"

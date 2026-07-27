#!/usr/bin/env bash
# Nmap Multi V2: Device Initialization Entry Point
# Usage: ./tools/device_init.sh [device_id]

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

cd "$PROJECT_ROOT" || exit 1

V1_INIT="/home/tech/nmap_multi_v1/device_init.sh"
if [ -f "$V1_INIT" ]; then
    echo "[*] Executing device initialization modules ($V1_INIT)..."
    exec bash "$V1_INIT" "$@"
else
    echo "[*] Executing V2 Python device initialization pipeline..."
    exec python3 "$PROJECT_ROOT/src/core/init_pipeline.py" "$@"
fi

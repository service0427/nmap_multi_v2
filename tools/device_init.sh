#!/usr/bin/env bash
# Nmap Multi V2: Device Initialization Entry Point
# Usage: ./tools/device_init.sh [device_id]

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

cd "$PROJECT_ROOT" || exit 1

echo "[*] Executing V2 Python device initialization pipeline..."
exec python3 "$PROJECT_ROOT/src/core/init_pipeline.py" "$@"

#!/usr/bin/env bash
# tools/sync_modems.sh: Nmap Multi V2: LTE modem traffic sync daemon wrapper

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
exec python3 "$SCRIPT_DIR/sync_modems.py" "$@"

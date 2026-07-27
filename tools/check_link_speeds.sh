#!/usr/bin/env bash
# tools/check_link_speeds.sh: Shell wrapper to query real-time traffic statistics from Huawei modems

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
exec python3 "$SCRIPT_DIR/check_link_speeds.py" "$@"

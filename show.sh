#!/bin/bash
# Nmap Multi V2 Monitoring Script Wrapper
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/tools/show_session_stats.py" "$@"

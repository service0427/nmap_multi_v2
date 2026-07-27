#!/usr/bin/env bash
# tools/show_session_stats.sh: Query and summarize execution performance stats from rotator_history/session_history.csv

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
exec python3 "$SCRIPT_DIR/show_session_stats.py" "$@"

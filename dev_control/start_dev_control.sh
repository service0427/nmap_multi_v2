#!/usr/bin/env bash
# Dev Control System Launcher (API: 5555, Web: 5001)

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR" || exit 1

echo "========================================================================"
echo "🚀 Launching Dev Control System Services..."
echo "  • Control API Server  : http://0.0.0.0:5555"
echo "  • Web Control UI      : http://0.0.0.0:5001"
echo "========================================================================"

# Kill old instances if any
pkill -f "dev_control/api/server.py" 2>/dev/null
pkill -f "dev_control/web/app.py" 2>/dev/null

# Start API Server on 5555 in background
python3 api/server.py &
API_PID=$!

# Start Web Server on 5001 in background
python3 web/app.py &
WEB_PID=$!

echo "[✓] Dev Control System launched successfully! (API PID: $API_PID | Web PID: $WEB_PID)"
wait

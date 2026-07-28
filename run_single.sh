#!/usr/bin/env bash
# Nmap Multi V2: Pure Single Device Launcher (V1 Direct Port)

BASE_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$BASE_DIR" || exit 1

DEV_ID=$1
shift

if [ -z "$DEV_ID" ]; then
    echo "Usage: ./run_single.sh <DEVICE_ID/INDEX> [--id TARGET_ID]"
    exit 1
fi

RESET_MODE=true
CLOSE_ON_EXIT=true
NO_FILTER="true"
TARGET_ID=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --id) TARGET_ID="$2"; shift 2 ;;
        *) shift ;;
    esac
done

PKG_NAME="com.nhn.android.nmap"
GPS_PKG="com.rosteam.gpsemulator"

export PATH=$PATH:/usr/local/bin:$HOME/.local/bin

check_cmd() {
    if ! command -v "$1" &> /dev/null; then
        if [ -f "$HOME/.local/bin/$1" ]; then
            export PATH="$PATH:$HOME/.local/bin"
        elif [ -f "/usr/local/bin/$1" ]; then
            export PATH="$PATH:/usr/local/bin"
        else
            return 1
        fi
    fi
    return 0
}

if ! check_cmd "mitmdump"; then echo -e "\e[1;31m[-] mitmdump not found. Try: pip3 install mitmproxy\e[0m"; exit 1; fi
if ! check_cmd "frida"; then echo -e "\e[1;31m[-] frida not found. Try: pip3 install frida-tools\e[0m"; exit 1; fi

CYAN="\e[1;36m"; GREEN="\e[1;32m"; YELLOW="\e[1;33m"; RED="\e[1;31m"; NC="\e[0m"

CONNECTED_DEVICES=($(adb devices | grep -w "device" | awk '{print $1}'))
NUM_CONNECTED=${#CONNECTED_DEVICES[@]}

if [[ "$DEV_ID" =~ ^[0-9]+$ ]]; then
    DEV_INDEX=$((DEV_ID - 1))
    if [ $DEV_INDEX -lt 0 ] || [ $DEV_INDEX -ge $NUM_CONNECTED ]; then
        echo "[-] Invalid index: $DEV_ID (Only $NUM_CONNECTED devices connected)"
        exit 1
    fi
    DEV_ID=${CONNECTED_DEVICES[$DEV_INDEX]}
else
    FOUND=false
    for d in "${CONNECTED_DEVICES[@]}"; do
        if [ "$d" == "$DEV_ID" ]; then FOUND=true; break; fi
    done
    if [ "$FOUND" = false ]; then
        echo "[-] Device $DEV_ID not connected or not found!"
        exit 1
    fi
    for i in "${!CONNECTED_DEVICES[@]}"; do
        if [ "${CONNECTED_DEVICES[$i]}" == "$DEV_ID" ]; then DEV_INDEX=$i; break; fi
    done
fi

BASE_MITM_PORT=30000
MITM_PORT=$((BASE_MITM_PORT + DEV_INDEX + 1))
FRIDA_PORT=$((MITM_PORT + 10000))

ALIAS=$(adb -s "$DEV_ID" shell getprop ro.product.model | tr -d '\r')
ALIAS=${ALIAS#SM-}
if [ -z "$ALIAS" ]; then ALIAS="UnknownDevice"; fi

export NMAP_ORIG_SSAID=""
export NMAP_ORIG_ADID=""
export NMAP_ORIG_IDFV=""
export NMAP_ORIG_NI=""
export NMAP_ORIG_TOKEN=""
export NMAP_NO_FILTER="true"

echo "============================================================"
echo "   NMAP V2 PURE ORIGINAL FETCH: $ALIAS ($DEV_ID)"
echo "   MITM:$MITM_PORT | FRIDA:$FRIDA_PORT | TARGET:${TARGET_ID:-None}"
echo "   Mode: Reset=ON, CloseOnExit=ON, Filtering=OFF"
echo "============================================================"

# --- V1 Strict Screen Orientation Lock (Portrait Only) ---
adb -s "$DEV_ID" shell "settings put system accelerometer_rotation 0" >/dev/null 2>&1
adb -s "$DEV_ID" shell "settings put system user_rotation 0" >/dev/null 2>&1
adb -s "$DEV_ID" shell "wm set-ignore-orientation-request true" >/dev/null 2>&1 || true
adb -s "$DEV_ID" shell "wm fixed-to-user-rotation enabled" >/dev/null 2>&1 || true
adb -s "$DEV_ID" shell "su -c 'settings put system volume_music 0; settings put system volume_notification 0; settings put system volume_ring 0; settings put system volume_system 0'" >/dev/null 2>&1

# --- V1 MITM CA Cert Verification & Magisk Module Check ---
CERT_PATH="$HOME/.mitmproxy/mitmproxy-ca-cert.pem"
if [ ! -f "$CERT_PATH" ]; then
    echo -e "${YELLOW}[!] Host mitmproxy CA cert missing. Auto-generating...${NC}"
    if command -v mitmdump >/dev/null 2>&1; then
        mitmdump &
        TMP_MITM_PID=$!
        sleep 2
        kill $TMP_MITM_PID 2>/dev/null
    fi
fi

CERT_HASH=$(openssl x509 -inform PEM -subject_hash_old -in "$CERT_PATH" 2>/dev/null | head -1)
if [ -n "$CERT_HASH" ]; then
    HAS_SU=$(adb -s "$DEV_ID" shell "which su" 2>/dev/null | tr -d '\r')
    [ -z "$HAS_SU" ] && HAS_SU="su"
    
    # Check if cert exists in /data/misc/user/0/cacerts-added and Magisk system dir
    CERT_INSTALLED=$(adb -s "$DEV_ID" shell "$HAS_SU -c '[ -f /data/misc/user/0/cacerts-added/$CERT_HASH.0 ] && echo YES || echo NO'" 2>/dev/null | tr -d '\r')
    
    if [ "$CERT_INSTALLED" != "YES" ]; then
        echo -e "${YELLOW}[!] Injecting MITM CA Certificate ($CERT_HASH.0) to system stores...${NC}"
        adb -s "$DEV_ID" push "$CERT_PATH" "/data/local/tmp/$CERT_HASH.0" >/dev/null 2>&1
        
        adb -s "$DEV_ID" shell "$HAS_SU -c '
            mkdir -p /data/misc/user/0/cacerts-added
            cp /data/local/tmp/$CERT_HASH.0 /data/misc/user/0/cacerts-added/$CERT_HASH.0
            chown system:system /data/misc/user/0/cacerts-added/$CERT_HASH.0
            chmod 644 /data/misc/user/0/cacerts-added/$CERT_HASH.0
            
            if [ -d /data/adb/modules/trustusercerts ]; then
                mkdir -p /data/adb/modules/trustusercerts/system/etc/security/cacerts
                cp /data/local/tmp/$CERT_HASH.0 /data/adb/modules/trustusercerts/system/etc/security/cacerts/$CERT_HASH.0
                chown root:root /data/adb/modules/trustusercerts/system/etc/security/cacerts/$CERT_HASH.0
                chmod 644 /data/adb/modules/trustusercerts/system/etc/security/cacerts/$CERT_HASH.0
                chcon u:object_r:system_security_cacerts_file:s0 /data/adb/modules/trustusercerts/system/etc/security/cacerts/$CERT_HASH.0 2>/dev/null
            fi
            rm -f /data/local/tmp/$CERT_HASH.0
        '" >/dev/null 2>&1
        
        echo -e "${YELLOW}[!] New cert injected. Rebooting device to apply Magisk trustusercerts mount...${NC}"
        adb -s "$DEV_ID" reboot
        echo -e "${YELLOW}[!] Waiting for device to come back online...${NC}"
        adb -s "$DEV_ID" wait-for-device
        sleep 5
    fi
fi

DATE_STR=$(date +%Y%m%d); TIME_STR=$(date +%H%M%S)
LOG_DIR="logs/init/${DEV_ID}/${DATE_STR}/${TIME_STR}_original"
mkdir -p "$LOG_DIR"
export CAPTURE_LOG_DIR="$(realpath "$LOG_DIR")"

echo -e "${CYAN}[$ALIAS]${NC} Cleaning up and performing Data Purge..."
adb -s "$DEV_ID" shell am force-stop $PKG_NAME
adb -s "$DEV_ID" shell am force-stop $GPS_PKG
adb -s "$DEV_ID" shell settings put global http_proxy :0 2>/dev/null
pkill -f "mitmdump.*$MITM_PORT" 2>/dev/null

if [ "$RESET_MODE" = true ]; then
    HAS_SU=$(adb -s "$DEV_ID" shell "which su" 2>/dev/null | tr -d '\r')
    if [ -z "$HAS_SU" ]; then
        HAS_SU=$(adb -s "$DEV_ID" shell "ls /system/bin/su /system/xbin/su /sbin/su 2>/dev/null" | head -1 | tr -d '\r')
    fi
    [ -z "$HAS_SU" ] && HAS_SU="su"
    adb -s "$DEV_ID" shell "$HAS_SU -c \"find /data/data/$PKG_NAME -mindepth 1 -maxdepth 1 ! -name 'lib' -exec rm -rf {} +\""
fi

echo -e "${CYAN}[$ALIAS]${NC} Setting up Proxy Tunnel (localhost:$MITM_PORT)..."
adb -s "$DEV_ID" reverse tcp:"$MITM_PORT" tcp:"$MITM_PORT" >/dev/null 2>&1
adb -s "$DEV_ID" shell settings put global http_proxy localhost:"$MITM_PORT"

MITM_ADDON_SCRIPT="$BASE_DIR/src/lib/v1_single/mitm_addon.py"
MITM_LOG="$CAPTURE_LOG_DIR/mitm.log"
PYTHONWARNINGS=ignore nohup mitmdump -p "$MITM_PORT" -s "$MITM_ADDON_SCRIPT" --ssl-insecure --listen-host 0.0.0.0 --set flow_detail=0 > "$MITM_LOG" 2>&1 &
MITM_PID=$!

# Pre-flight: Ensure frida-server is running on device
HAS_SU=$(adb -s "$DEV_ID" shell "which su" 2>/dev/null | tr -d '\r')
[ -z "$HAS_SU" ] && HAS_SU="su"

FRIDA_SERVER_PID=$(adb -s "$DEV_ID" shell "$HAS_SU -c 'pidof frida-server'" 2>/dev/null | tr -d '\r\n')
if [ -z "$FRIDA_SERVER_PID" ]; then
    echo -e "${YELLOW}[$ALIAS] Starting frida-server daemon on device...${NC}"
    adb -s "$DEV_ID" shell "$HAS_SU -c '/system/bin/frida-server &'" >/dev/null 2>&1
    sleep 1.5
fi

adb -s "$DEV_ID" forward --remove tcp:$FRIDA_PORT 2>/dev/null
adb -s "$DEV_ID" forward tcp:$FRIDA_PORT tcp:27042 >/dev/null 2>&1
FRIDA_LOG="$CAPTURE_LOG_DIR/frida.log"

# Dismiss Keyguard & Start Naver Map
adb -s "$DEV_ID" shell "input keyevent 224; wm dismiss-keyguard" >/dev/null 2>&1
echo -e "${YELLOW}[$ALIAS] Launching Naver Map (LaunchActivity)...${NC}"
adb -s "$DEV_ID" shell "am start -n com.nhn.android.nmap/com.naver.map.LaunchActivity" > /dev/null 2>&1

PID=""
for i in {1..10}; do
    PID=$(adb -s "$DEV_ID" shell pidof "$PKG_NAME" 2>/dev/null | awk '{print $1}' | tr -d '\r\n')
    [ -n "$PID" ] && break
    sleep 1
done

if [ -z "$PID" ]; then
    adb -s "$DEV_ID" shell "am start -n com.nhn.android.nmap/com.naver.map.LaunchActivity" > /dev/null 2>&1
    sleep 3
    PID=$(adb -s "$DEV_ID" shell pidof "$PKG_NAME" 2>/dev/null | awk '{print $1}' | tr -d '\r\n')
fi

HOOKS_DIR="$BASE_DIR/src/lib/v1_single/hooks"
if [ -n "$PID" ]; then
    echo -e "${GREEN}[$ALIAS] App started with PID: $PID. Attaching Frida...${NC}"
    nohup frida -H 127.0.0.1:$FRIDA_PORT --runtime=v8 -p "$PID" \
        -l "$HOOKS_DIR/survival_light.js" \
        -l "$HOOKS_DIR/network_hook.js" \
        -l "$HOOKS_DIR/data_collector.js" \
        --no-auto-reload > "$FRIDA_LOG" 2>&1 &
    FRIDA_PID=$!
fi

sleep 3

echo -e "${GREEN}============================================================${NC}"
echo -e " [✓] [$ALIAS] SYSTEM READY. Original Value Logging..."
echo -e " [!] Log Directory: $CAPTURE_LOG_DIR"
echo -e "${GREEN}============================================================${NC}"

cleanup() {
    echo -e "\n${YELLOW}[$ALIAS] Stopping processes...${NC}"
    kill -9 $MITM_PID $FRIDA_PID 2>/dev/null
    adb -s "$DEV_ID" shell am force-stop $PKG_NAME
    adb -s "$DEV_ID" shell settings put global http_proxy :0 2>/dev/null
    adb -s "$DEV_ID" reverse --remove-all 2>/dev/null
    adb -s "$DEV_ID" forward --remove-all 2>/dev/null
    exit 0
}
trap cleanup INT TERM

echo -e "${YELLOW}[!] Monitoring for complete nlogapp capture...${NC}"

while true; do
    TARGET_FILE=$(find "$CAPTURE_LOG_DIR" -name "*POST_nlogapp.json" 2>/dev/null | head -n 1)
    if [ -n "$TARGET_FILE" ]; then
        sleep 1
        ADID=$(jq -r '.request.body.usr.adid // empty' "$TARGET_FILE" 2>/dev/null)
        SSAID=$(jq -r '.request.body.usr.ssaid // empty' "$TARGET_FILE" 2>/dev/null)
        IDFV=$(jq -r '.request.body.usr.idfv // empty' "$TARGET_FILE" 2>/dev/null)
        NI=$(jq -r '.request.body.usr.ni // empty' "$TARGET_FILE" 2>/dev/null)
        
        FULL_NLOG_ID=$(jq -r '.request.body.evts[0].nlog_id // empty' "$TARGET_FILE" 2>/dev/null)
        TOKEN=$(echo "$FULL_NLOG_ID" | awk -F'.' '{print $NF}')
        
        if [ -n "$ADID" ] && [ "$ADID" != "null" ] && \
           [ -n "$SSAID" ] && [ "$SSAID" != "null" ] && \
           [ -n "$IDFV" ] && [ "$IDFV" != "null" ] && \
           [ -n "$NI" ] && [ "$NI" != "null" ]; then
            
            echo -e "${GREEN}[✓] Complete Data Set Found: $(basename "$TARGET_FILE")${NC}"
            echo -e "\n${CYAN}--- GENERATED SQL QUERY ---${NC}"
            SQL="INSERT INTO \`devices\`(\`device_id\`, \`alias\`, \`orig_ssaid\`, \`orig_adid\`, \`orig_idfv\`, \`orig_ni\`, \`orig_token\`) VALUES ('$DEV_ID', '$ALIAS', '$SSAID', '$ADID', '$IDFV', '$NI', '$TOKEN');"
            echo -e "$SQL"
            echo -e "${CYAN}----------------------------${NC}\n"
            
            mkdir -p "logs"
            echo "$SQL" >> "logs/insert.txt"
            echo -e "${YELLOW}[!] Query appended to: $BASE_DIR/logs/insert.txt${NC}"
            
            SQL_UPDATE="UPDATE \`devices\` SET \`alias\`='$ALIAS', \`orig_ssaid\`='$SSAID', \`orig_adid\`='$ADID', \`orig_idfv\`='$IDFV', \`orig_ni\`='$NI', \`orig_token\`='$TOKEN' WHERE \`device_id\`='$DEV_ID';"
            echo "$SQL_UPDATE" >> "logs/update.txt"
            echo -e "${YELLOW}[!] Query appended to: $BASE_DIR/logs/update.txt${NC}"
            
            cleanup
        else
            mv "$TARGET_FILE" "${TARGET_FILE}.incomplete" 2>/dev/null
        fi
    fi
    sleep 2
done

wait

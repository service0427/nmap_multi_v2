#!/usr/bin/env bash

# ============================================================
# Nmap Multi V2: Device BoringSSL Curl Recovery Script
# ============================================================

TARGET_DEVICE=$1
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CURL_BIN="$SCRIPT_DIR/install/curl-aarch64"

if [ ! -f "$CURL_BIN" ]; then
    echo "[-] Error: Local BoringSSL curl binary not found at $CURL_BIN"
    exit 1
fi

# Get connected devices
if [ -z "$TARGET_DEVICE" ]; then
    echo "[*] No target device specified. Checking all connected devices..."
    DEVICES=$(adb devices | grep -w "device" | awk '{print $1}')
else
    echo "[*] Targeting specific device: $TARGET_DEVICE"
    DEVICES=$TARGET_DEVICE
fi

if [ -z "$DEVICES" ]; then
    echo "[-] No devices connected."
    exit 1
fi

GREEN="\e[1;32m"
YELLOW="\e[1;33m"
RED="\e[1;31m"
NC="\e[0m"

for serial in $DEVICES; do
    echo "--------------------------------------------------------------------------------"
    
    MODEL_ALIAS=$(adb -s "$serial" shell "getprop ro.product.model" 2>/dev/null | tr -d '\r\n')
    MODEL_ALIAS=${MODEL_ALIAS#SM-}
    [ -z "$MODEL_ALIAS" ] && MODEL_ALIAS="Unknown"

    echo -e "📱 Device Audit Target: ${GREEN}$MODEL_ALIAS ($serial)${NC}"

    # 1. Root & SU Shell Audit
    HAS_SU=$(adb -s "$serial" shell "which su" 2>/dev/null | tr -d '\r\n')
    [ -z "$HAS_SU" ] && HAS_SU=$(adb -s "$serial" shell "ls /system/bin/su /system/xbin/su /sbin/su 2>/dev/null" | head -1 | tr -d '\r\n')
    [ -z "$HAS_SU" ] && HAS_SU="su"
    
    SU_CHECK=$(timeout 2 adb -s "$serial" shell "$HAS_SU -c 'id'" 2>/dev/null | tr -d '\r\n')
    if [[ "$SU_CHECK" == *"uid=0"* ]]; then
        echo -e "  [✓] Magisk Root Shell (su)  : ${GREEN}AUTHORIZED (uid=0)${NC}"
    else
        echo -e "  [!] Magisk Root Shell (su)  : ${RED}NOT AUTHORIZED / PENDING POPUP${NC}"
    fi

    # 2. Host mitmproxy CA Cert Trust Audit
    HOST_CERT_PATH="$HOME/.mitmproxy/mitmproxy-ca-cert.pem"
    CERT_HASH=""
    if [ -f "$HOST_CERT_PATH" ]; then
        CERT_HASH=$(openssl x509 -inform PEM -subject_hash_old -in "$HOST_CERT_PATH" 2>/dev/null | head -1)
    fi

    if [ -n "$CERT_HASH" ]; then
        USER_CERT_OK=$(adb -s "$serial" shell "$HAS_SU -c '[ -f /data/misc/user/0/cacerts-added/$CERT_HASH.0 ] && echo YES || echo NO'" 2>/dev/null | tr -d '\r\n')
        SYS_CERT_OK=$(adb -s "$serial" shell "$HAS_SU -c '[ -f /data/adb/modules/trustusercerts/system/etc/security/cacerts/$CERT_HASH.0 ] && echo YES || echo NO'" 2>/dev/null | tr -d '\r\n')
        
        if [ "$USER_CERT_OK" = "YES" ] && [ "$SYS_CERT_OK" = "YES" ]; then
            echo -e "  [✓] mitmproxy CA Cert ($CERT_HASH.0): ${GREEN}TRUSTED IN SYSTEM & MAGISK STORE${NC}"
        else
            echo -e "  [⚠️] mitmproxy CA Cert ($CERT_HASH.0): ${YELLOW}MISSING / REQUIRES INJECTION (User:$USER_CERT_OK, Sys:$SYS_CERT_OK)${NC}"
        fi
    else
        echo -e "  [!] mitmproxy CA Cert       : ${RED}HOST CERT FILE NOT FOUND ($HOST_CERT_PATH)${NC}"
    fi

    # 3. Backup and disable HTTP Proxy for direct connection test
    OLD_PROXY=$(adb -s "$serial" shell "settings get global http_proxy" 2>/dev/null | tr -d '\r\n')
    if [ "$OLD_PROXY" != ":0" ] && [ "$OLD_PROXY" != "null" ] && [ -n "$OLD_PROXY" ]; then
        adb -s "$serial" shell "settings put global http_proxy :0" >/dev/null 2>&1
    fi

    # 4. Check BoringSSL curl & Public IP
    has_device_curl=$(adb -s "$serial" shell "which curl" 2>/dev/null | tr -d '\r')
    is_boring="NO"
    if [ -n "$has_device_curl" ]; then
        is_boring=$(adb -s "$serial" shell "curl --version 2>/dev/null" | grep -q "BoringSSL" && echo "YES" || echo "NO")
    fi
    
    is_working="NO"
    test_ip=""
    if [ "$is_boring" = "YES" ]; then
        test_ip=$(adb -s "$serial" shell "curl -s -4 --connect-timeout 3 https://ifconfig.me" 2>/dev/null | tr -d '\r\n')
        if [[ "$test_ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            is_working="YES"
        else
            resolved_ip=$(adb -s "$serial" shell "ping -c 1 -W 2 ifconfig.me | head -n 1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+'" 2>/dev/null | tr -d '\r\n')
            [ -z "$resolved_ip" ] && resolved_ip="34.160.111.145"
            test_ip=$(adb -s "$serial" shell "curl -s -4 --connect-timeout 3 --resolve ifconfig.me:443:$resolved_ip https://ifconfig.me" 2>/dev/null | tr -d '\r\n')
            if [[ "$test_ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
                is_working="YES"
            fi
        fi
    fi
    
    if [ "$is_working" = "YES" ]; then
        echo -e "  [✓] BoringSSL Binary & Network : ${GREEN}ACTIVE (Public IP: $test_ip)${NC}"
        adb -s "$serial" shell "su -c 'rm -f /system/etc/resolv.conf /etc/resolv.conf'" >/dev/null 2>&1
        
        if [ "$OLD_PROXY" != ":0" ] && [ "$OLD_PROXY" != "null" ] && [ -n "$OLD_PROXY" ]; then
            adb -s "$serial" shell "settings put global http_proxy $OLD_PROXY" >/dev/null 2>&1
        fi
        continue
    fi

    # 3. Find su
    HAS_SU=$(adb -s "$serial" shell "which su" 2>/dev/null | tr -d '\r')
    if [ -z "$HAS_SU" ]; then
        HAS_SU=$(adb -s "$serial" shell "ls /system/bin/su /system/xbin/su /sbin/su 2>/dev/null" | head -1 | tr -d '\r')
    fi
    
    if [ -z "$HAS_SU" ]; then
        echo -e "  ${RED}[!] Root (su) not found. Cannot overwrite system curl.${NC}"
        if [ "$OLD_PROXY" != ":0" ] && [ "$OLD_PROXY" != "null" ] && [ -n "$OLD_PROXY" ]; then
            adb -s "$serial" shell "settings put global http_proxy $OLD_PROXY" >/dev/null 2>&1
        fi
        continue
    fi
    
    # 4. Push and deploy native BoringSSL curl
    echo "  - Pushing BoringSSL curl to /data/local/tmp/curl..."
    adb -s "$serial" push "$CURL_BIN" /data/local/tmp/curl >/dev/null 2>&1
    
    echo "  - Remounting system and deploying curl to /system/bin/curl..."
    adb -s "$serial" shell "$HAS_SU -c 'umount /system/bin/curl'" >/dev/null 2>&1
    adb -s "$serial" shell "$HAS_SU -c 'mount -o rw,remount / 2>/dev/null || mount -o rw,remount /system 2>/dev/null; mount -o rw,remount /system/bin 2>/dev/null'" >/dev/null 2>&1
    adb -s "$serial" shell "$HAS_SU -c 'cp /data/local/tmp/curl /system/bin/curl && chmod 755 /system/bin/curl; rm -f /system/etc/resolv.conf; rm -f /etc/resolv.conf; rm -f /data/local/tmp/curl'" >/dev/null 2>&1
    
    # 5. Verify native BoringSSL curl via HTTPS
    echo "  - Verifying HTTPS connection..."
    TEST_IP=$(adb -s "$serial" shell "curl -sS -4 --connect-timeout 5 https://ifconfig.me 2>&1" | tr -d '\r\n')
    
    if [[ ! "$TEST_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        resolved_ip=$(adb -s "$serial" shell "ping -c 1 -W 2 ifconfig.me | head -n 1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+'" 2>/dev/null | tr -d '\r\n')
        if [ -z "$resolved_ip" ]; then
            resolved_ip="34.160.111.145"
        fi
        TEST_IP=$(adb -s "$serial" shell "curl -sS -4 --connect-timeout 5 --resolve ifconfig.me:443:$resolved_ip https://ifconfig.me 2>&1" | tr -d '\r\n')
    fi
    
    if [[ "$TEST_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        echo -e "  ${GREEN}[✓] Recovery SUCCESS! Real IP detected: $TEST_IP${NC}"
    else
        resolved_ip=$(adb -s "$serial" shell "ping -c 1 -W 2 ifconfig.me | head -n 1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+'" 2>/dev/null | tr -d '\r\n')
        if [ -z "$resolved_ip" ]; then
            resolved_ip="34.160.111.145"
        fi
        TEST_IP_K=$(adb -s "$serial" shell "curl -k -sS -4 --connect-timeout 5 --resolve ifconfig.me:443:$resolved_ip https://ifconfig.me 2>&1" | tr -d '\r\n')
        
        if [[ "$TEST_IP_K" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            echo -e "  ${YELLOW}[⚠️] curl works with -k, but standard HTTPS failed. Output: $TEST_IP_K${NC}"
        else
            echo -e "  ${RED}[!] Verification FAILED. Output: $TEST_IP (Fallback: $TEST_IP_K)${NC}"
            device_proxy=$(adb -s "$serial" shell "settings get global http_proxy" 2>/dev/null | tr -d '\r\n')
            cert_details=$(adb -s "$serial" shell "curl -Iv -4 --connect-timeout 5 --resolve ifconfig.me:443:$resolved_ip https://ifconfig.me 2>&1" | grep -E 'Server certificate|subject|issuer|subjectAltName|SSL connection|expire date' | sed 's/^/      /')
            echo -e "  ${YELLOW}[Diagnostics]${NC}"
            echo -e "    - Resolved IP: $resolved_ip"
            echo -e "    - Device Global Proxy: $device_proxy"
            echo -e "    - Certificate Details:"
            if [ -n "$cert_details" ]; then
                echo "$cert_details"
            else
                echo "      (Could not retrieve certificate details)"
            fi
        fi
    fi

    # Restore proxy
    if [ "$OLD_PROXY" != ":0" ] && [ "$OLD_PROXY" != "null" ] && [ -n "$OLD_PROXY" ]; then
        adb -s "$serial" shell "settings put global http_proxy $OLD_PROXY" >/dev/null 2>&1
    fi
done

echo "--------------------------------------------------"
echo -e "${GREEN}[✓] BoringSSL Curl Recovery complete.${NC}"

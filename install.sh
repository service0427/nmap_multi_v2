#!/usr/bin/env bash
# Nmap Multi V2: 통합 시스템 인프라 및 관리 제어 센터 (단일 통합 파일)
# 사용법: ./install.sh [옵션]  또는  sudo ./install.sh [옵션]

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR" || exit 1

CYAN="\033[0;36m"
GREEN="\033[0;32m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
BLUE="\033[0;34m"
BOLD="\033[1m"
NC="\033[0m"

# 루트/sudo 권한 자동 승계 함수
ensure_sudo() {
    if [ "$EUID" -ne 0 ]; then
        echo -e "${YELLOW}[🔑] 해당 작업은 sudo(root) 권한이 필요합니다. 권한 승계를 진행합니다...${NC}"
        exec sudo bash "$0" "$@"
    fi
}

# ---------------------------------------------------------
# 1. 전체 시스템 & LTE 인프라 구동 환경 설치 (sudo 전용)
# ---------------------------------------------------------
run_infra_setup() {
    ensure_sudo "$@"
    
    echo -e "\n${CYAN}============================================================${NC}"
    echo -e "${BOLD} 🚀 [1/6] 필수 시스템 의존성 패키지 및 파이썬 모듈 설치${NC}"
    echo -e "${CYAN}============================================================${NC}"
    apt-get update -qq > /dev/null 2>&1 || true
    apt-get install -y -qq \
        adb jq python3-pip curl net-tools iproute2 \
        isc-dhcp-client network-manager lsof procps udev iptables > /dev/null 2>&1

    PIP_BREAK_FLAGS=""
    if python3 -m pip install --help 2>/dev/null | grep -q "break-system-packages"; then
        PIP_BREAK_FLAGS="--break-system-packages"
    fi

    python3 -m pip install --quiet $PIP_BREAK_FLAGS \
        mitmproxy frida-tools blackboxprotobuf huawei-lte-api flask requests psutil 2>/dev/null || true

    echo -e "${GREEN}[✓] APT 핵심 패키지 및 파이썬 라이브러리 구성 완료.${NC}"

    echo -e "\n${CYAN}============================================================${NC}"
    echo -e "${BOLD} 🧹 [2/6] 레거시 네트워크 / udev 설정 정리 (충돌 방지)${NC}"
    echo -e "${CYAN}============================================================${NC}"
    for rule in /etc/udev/rules.d/70-persistent-net.rules /etc/udev/rules.d/99-lte-proxy.rules; do
        if [ -f "$rule" ]; then
            echo -e "   > 구버전 udev 규칙 제거: $rule"
            rm -f "$rule"
        fi
    done

    if [ -d "/etc/netplan" ]; then
        for yaml in /etc/netplan/*.yaml /etc/netplan/*.yml; do
            [ -f "$yaml" ] || continue
            if [ "$(basename "$yaml")" != "00-installer-config.yaml" ]; then
                if grep -qE "lte|enx001e101f0000" "$yaml" 2>/dev/null; then
                    echo -e "   > 구버전 Netplan 설정 제거: $yaml"
                    rm -f "$yaml"
                fi
            fi
        done
    fi

    if [ -f "/etc/iproute2/rt_tables" ]; then
        if grep -q "lte" /etc/iproute2/rt_tables 2>/dev/null; then
            echo -e "   > 레거시 lte 라우팅 테이블 제거 (/etc/iproute2/rt_tables)"
            sed -i '/lte/d' /etc/iproute2/rt_tables
        fi
    fi
    udevadm control --reload-rules 2>/dev/null || true

    echo -e "\n${CYAN}============================================================${NC}"
    echo -e "${BOLD} ⚙️ [3/6] 커널 sysctl 파라미터 최적화 (ARP/MAC 격리)${NC}"
    echo -e "${CYAN}============================================================${NC}"
    cat <<EOF > /etc/sysctl.d/99-lte-proxy.conf
net.ipv4.conf.all.arp_ignore=1
net.ipv4.conf.all.arp_announce=2
net.ipv4.conf.all.rp_filter=2
EOF
    sysctl -p /etc/sysctl.d/99-lte-proxy.conf > /dev/null 2>&1
    echo -e "${GREEN}[✓] ARP 및 멀티 MAC 커널 격리 설정 완료.${NC}"

    echo -e "\n${CYAN}============================================================${NC}"
    echo -e "${BOLD} 🛡️ [4/6] 글로벌 DNS 고정 및 네트워크 드롭 방지${NC}"
    echo -e "${CYAN}============================================================${NC}"
    DNS_RESTART=0
    if [ ! -f /etc/systemd/resolved.conf ] || ! grep -q "DNS=8.8.8.8 8.8.4.4" /etc/systemd/resolved.conf; then
        cat << EOF > /etc/systemd/resolved.conf
[Resolve]
DNS=8.8.8.8 8.8.4.4
FallbackDNS=1.1.1.1 1.0.0.1
Domains=~.
EOF
        DNS_RESTART=1
    fi

    mkdir -p /etc/NetworkManager/conf.d
    if [ ! -f /etc/NetworkManager/conf.d/dns.conf ] || ! grep -q "dns=systemd-resolved" /etc/NetworkManager/conf.d/dns.conf; then
        cat << EOF > /etc/NetworkManager/conf.d/dns.conf
[main]
dns=systemd-resolved
EOF
        DNS_RESTART=1
    fi

    if [ "$DNS_RESTART" -eq 1 ]; then
        systemctl restart systemd-resolved 2>/dev/null || true
        systemctl restart NetworkManager 2>/dev/null || true
        echo -e "${GREEN}[✓] DNS 고정 설정 및 관련 서비스 재시작 완료.${NC}"
    else
        echo -e "${GREEN}[✓] DNS가 이미 8.8.8.8로 고정되어 있습니다.${NC}"
    fi

    echo -e "\n${CYAN}============================================================${NC}"
    echo -e "${BOLD} 🌐 [5/6] 메인 유선 WAN 인터페이스 보호 설정 (Metric 100)${NC}"
    echo -e "${CYAN}============================================================${NC}"
    WIRED_IFACE=$(nmcli -t -f DEVICE,TYPE,STATE device status 2>/dev/null | grep ethernet | grep connected | cut -d: -f1 | head -n 1)
    if [ -z "$WIRED_IFACE" ]; then
        WIRED_IFACE=$(ip route show default | grep -vE "lte|usb|enx" | awk '{print $5}' | head -n 1)
    fi
    if [ -z "$WIRED_IFACE" ]; then
        WIRED_IFACE=$(ip -o link show | awk -F': ' '{print $2}' | grep -E "^(enp|eth|eno)" | grep -vE "lte|usb" | head -n 1)
    fi

    if [ -n "$WIRED_IFACE" ]; then
        echo -e "   > 메인 유선 인터페이스 감지됨: ${CYAN}$WIRED_IFACE${NC}"
        NM_CONN=$(nmcli -t -f NAME,DEVICE connection show active 2>/dev/null | grep ":$WIRED_IFACE$" | cut -d: -f1 || true)
        if [ -n "$NM_CONN" ]; then
            nmcli connection modify "$NM_CONN" ipv4.route-metric 100 2>/dev/null || true
            nmcli connection up "$NM_CONN" 2>/dev/null || true
        fi
    else
        echo -e "${YELLOW}[!] 메인 유선망을 자동으로 찾지 못했습니다. 기본값(eth0)을 사용합니다.${NC}"
        WIRED_IFACE="eth0"
    fi

    echo -e "\n${CYAN}============================================================${NC}"
    echo -e "${BOLD} 📡 [6/6] lte-sync 라우팅 데몬 생성 및 systemd/udev 서비스 등록${NC}"
    echo -e "${CYAN}============================================================${NC}"
    
    cat << 'EOF' > /usr/local/bin/lte-sync
#!/usr/bin/env bash
exec python3 /home/tech/nmap_multi_v2/tools/fix_lte_interfaces.sh "$@"
EOF
    chmod +x /usr/local/bin/lte-sync

    # Udev 규칙 등록
    echo 'ACTION=="add", SUBSYSTEM=="net", KERNEL=="eth*|usb*|enx*", RUN+="/usr/local/bin/lte-sync"' > /etc/udev/rules.d/99-lte-auto-sync.rules
    echo 'ACTION=="add", SUBSYSTEM=="net", ATTR{address}=="00:1e:10:1f:00:00", RUN+="/usr/local/bin/lte-sync"' >> /etc/udev/rules.d/99-lte-auto-sync.rules
    udevadm control --reload-rules 2>/dev/null || true

    # Systemd 서비스 등록
    cat << EOF > /etc/systemd/system/lte-sync.service
[Unit]
Description=Nmap Multi V2 LTE Routing Sync Service
After=network-online.target NetworkManager.service
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/lte-sync
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload 2>/dev/null || true
    systemctl enable lte-sync.service 2>/dev/null || true

    # 연결된 모뎀 즉시 동기화 실행
    python3 "$SCRIPT_DIR/tools/fix_lte_interfaces.sh" || true

    echo -e "\n${CYAN}============================================================${NC}"
    echo -e "${GREEN} ✅ Nmap Multi V2 전체 시스템 인프라 구축 완료!${NC}"
    echo -e "${CYAN}============================================================${NC}"
}

# ---------------------------------------------------------
# 2. PCIe / USB xHCI 사용 한계 및 대역폭 점검 (sudo 필요)
# ---------------------------------------------------------
run_usb_limits() {
    ensure_sudo "$@"
    USB_SCRIPT="$SCRIPT_DIR/tools/check_usb_limits.sh"
    if [ ! -f "$USB_SCRIPT" ]; then
        echo -e "${RED}[-] 오류: $USB_SCRIPT 파일을 찾을 수 없습니다.${NC}"
        exit 1
    fi
    chmod +x "$USB_SCRIPT"
    python3 "$USB_SCRIPT"
}

# ---------------------------------------------------------
# 3. LTE 모뎀 라우팅 / 서브넷 즉시 동기화 (sudo 필요)
# ---------------------------------------------------------
run_lte_sync() {
    ensure_sudo "$@"
    if [ -f "$SCRIPT_DIR/tools/fix_lte_interfaces.sh" ]; then
        python3 "$SCRIPT_DIR/tools/fix_lte_interfaces.sh"
    else
        echo -e "${RED}[-] 오류: fix_lte_interfaces.sh 데몬을 찾을 수 없습니다.${NC}"
        exit 1
    fi
}

# ---------------------------------------------------------
# 4. 호스트 환경 & 네이버 지도 자산 점검 (일반 사용자 가능)
# ---------------------------------------------------------
run_user_setup() {
    echo -e "\n${YELLOW}[1/3] 호스트 파이썬 패키지 의존성 점검 중...${NC}"
    PIP_BREAK_FLAGS=""
    if python3 -m pip install --help 2>/dev/null | grep -q "break-system-packages"; then
        PIP_BREAK_FLAGS="--break-system-packages"
    fi
    python3 -m pip install --quiet $PIP_BREAK_FLAGS --upgrade pip 2>/dev/null || true
    python3 -m pip install --quiet $PIP_BREAK_FLAGS mitmproxy blackboxprotobuf huawei-lte-api flask requests psutil 2>/dev/null || true
    echo -e "${GREEN}[✓] 파이썬 패키지 검증 완료.${NC}"

    echo -e "\n${YELLOW}[2/3] 네이버 지도 APK 자산 점검 중...${NC}"
    TARGET_NMAP_VERSION="6.8.1.1"
    has_nmap_apk=false
    INSTALL_DIR="$SCRIPT_DIR/install"

    if [ -d "$INSTALL_DIR/naver_map_${TARGET_NMAP_VERSION}" ] && [ -f "$INSTALL_DIR/naver_map_${TARGET_NMAP_VERSION}/base.apk" ]; then
        has_nmap_apk=true
    fi

    if [ "$has_nmap_apk" = false ]; then
        echo -e "${YELLOW}[*] 네이버 지도 v${TARGET_NMAP_VERSION} 자산이 없습니다. 다운로드를 시작합니다...${NC}"
        if [ -f "/home/tech/nmap_multi_v1/update_nmap.sh" ]; then
            bash "/home/tech/nmap_multi_v1/update_nmap.sh" --non-interactive
        else
            echo -e "${RED}[-] 오류: update_nmap.sh 파일이 없습니다.${NC}"
        fi
    else
        echo -e "${GREEN}[✓] 네이버 지도 자산 확인 완료: $INSTALL_DIR/naver_map_${TARGET_NMAP_VERSION}/base.apk${NC}"
    fi

    echo -e "\n${YELLOW}[3/3] LTE 인프라 (lte-sync) 설치 여부 점검...${NC}"
    if [ -x "/usr/local/bin/lte-sync" ] && [ -f "/etc/udev/rules.d/99-lte-auto-sync.rules" ]; then
        echo -e "${GREEN}[✓] LTE 라우터 동기화 데몬(lte-sync)이 시스템에 정상 설치되어 있습니다.${NC}"
    else
        echo -e "${YELLOW}[!] 시스템 LTE 인프라가 아직 설치되지 않았습니다.${NC}"
        echo -e "    1번 메뉴 또는 ${CYAN}sudo ./install.sh --sudo${NC} 명령으로 설치를 완료해주세요."
    fi

    echo -e "\n${GREEN}[✓] 호스트 사용자 환경 점검 완료!${NC}"
}

# 도움말
print_help() {
    echo -e "${CYAN}============================================================${NC}"
    echo -e "${BOLD}   Nmap Multi V2: 명령어 대화형/플래그 옵션 안내${NC}"
    echo -e "${CYAN}============================================================${NC}"
    echo -e "사용법:"
    echo -e "  ${BOLD}./install.sh${NC}                         대화형 한국어 메뉴 대시보드 실행"
    echo -e "  ${BOLD}./install.sh --sudo${NC}  (또는 -1)       전체 시스템 및 LTE 인프라 설치 (sudo 권한 필요)"
    echo -e "  ${BOLD}./install.sh --usb${NC}   (또는 -2)       PCIe/USB xHCI 슬롯 및 엔드포인트 제한 점검 (sudo 필요)"
    echo -e "  ${BOLD}./install.sh --sync${NC}  (또는 -3)       LTE 모뎀 서브넷/PBR 라우팅 동기화 (sudo 필요)"
    echo -e "  ${BOLD}./install.sh --user${NC}  (또는 -4)       호스트 파이썬 환경 및 지도 자산 점검 (일반 권한 가능)"
    echo -e "  ${BOLD}./install.sh --help${NC}  (또는 -h)       도움말 출력"
    echo -e "${CYAN}============================================================${NC}"
    exit 0
}

# ---------------------------------------------------------
# 플래그 인자 직접 실행 모드 (Bypass Mode)
# ---------------------------------------------------------
if [ $# -gt 0 ]; then
    case "$1" in
        --sudo|--infra|--all|-1)
            run_infra_setup "$@"
            exit 0
            ;;
        --usb-limits|--usb|--limits|-2)
            run_usb_limits "$@"
            exit 0
            ;;
        --sync|--lte-sync|-3)
            run_lte_sync "$@"
            exit 0
            ;;
        --user|--host|-4)
            run_user_setup "$@"
            exit 0
            ;;
        --help|-h)
            print_help
            ;;
        *)
            echo -e "${RED}[-] 알 수 없는 옵션: $1${NC}"
            print_help
            ;;
    esac
fi

# ---------------------------------------------------------
# 대화형 프롬프트 대시보드 모드 (인자 없이 실행 시)
# ---------------------------------------------------------
PERM_LABEL=""
if [ "$EUID" -eq 0 ]; then
    PERM_LABEL="${GREEN}[현재 실행 권한: root / sudo 관리자]${NC}"
else
    PERM_LABEL="${YELLOW}[현재 실행 권한: 일반 사용자 (tech)]${NC}"
fi

echo -e "${CYAN}============================================================${NC}"
echo -e "${BOLD}   🚀 Nmap Multi V2: 대화형 시스템 통합 관리 대시보드${NC}"
echo -e "   $PERM_LABEL"
echo -e "${CYAN}============================================================${NC}"
echo -e " 수행하실 작업의 번호를 선택해주세요:\n"
echo -e "  ${BOLD}${GREEN}1)${NC} ${BOLD}전체 시스템 & LTE 인프라 구축${NC} (APT 패키지, sysctl 튜닝, DNS 고정, lte-sync)"
echo -e "     ${RED}🔒 [sudo/root 필수 권한]${NC} (선택 시 자동으로 sudo 승계 요청)\n"
echo -e "  ${BOLD}${GREEN}2)${NC} ${BOLD}PCIe / USB xHCI 연결 및 엔드포인트 한계 점검${NC} (슬롯 여유량 대시보드)"
echo -e "     ${RED}🔒 [sudo/root 필수 권한]${NC} (선택 시 자동으로 sudo 승계 요청)\n"
echo -e "  ${BOLD}${GREEN}3)${NC} ${BOLD}LTE 모뎀 서브넷 및 PBR 라우팅 동기화${NC} (lte11~lte30 즉시 바인딩)"
echo -e "     ${RED}🔒 [sudo/root 필수 권한]${NC} (선택 시 자동으로 sudo 승계 요청)\n"
echo -e "  ${BOLD}${GREEN}4)${NC} ${BOLD}호스트 환경 및 네이버 지도 자산 점검${NC} (파이썬 라이브러리 & APK 검증)"
echo -e "     ${BLUE}🔓 [일반 사용자 권한으로 즉시 가능]${NC}\n"
echo -e "  ${BOLD}${RED}5) 종료 (Exit) [기본값 - 엔터 입력 시]${NC}\n"
echo -e "${CYAN}============================================================${NC}"

read -p "작업 선택 [1-5] (기본값: 5 종료): " CHOICE

# 엔터만 쳤거나 빈값인 경우 5번(종료)으로 설정
CHOICE="${CHOICE:-5}"

case "$CHOICE" in
    1)
        run_infra_setup
        ;;
    2)
        run_usb_limits
        ;;
    3)
        run_lte_sync
        ;;
    4)
        run_user_setup
        ;;
    5|"")
        echo -e "${CYAN}[*] 프로그램을 종료합니다.${NC}"
        exit 0
        ;;
    *)
        echo -e "${RED}[-] 올바르지 않은 입력 '$CHOICE' 입니다. 프로그램을 종료합니다.${NC}"
        exit 1
        ;;
esac

# Nmap Multi V2: Consolidated Orchestration System

본 프로젝트는 60대의 모바일 단말기 및 멀티 모뎀 환경을 실시간으로 관리, 스케줄링 및 자동화하는 백엔드 코어 모듈의 Consolidated 개편 버전(V2)입니다. 기존 V1의 개별 쉘 파일 분할 구동 방식을 일원화하여 성능과 유연성을 향상시키고 다중 프로세스 간의 병목 현상을 방지하도록 재설계되었습니다.

---

## 📂 디렉토리 및 파일 구성

```text
nmap_multi_v2/
├── start.sh                 # 통합 기동 및 모뎀 진단 진입 스크립트
├── cmd.sh                   # concurrent 멀티디바이스 제어 CLI 도구
├── install.sh               # 호스트 종속성 설치 및 모바일 기기 초기화 진입점
├── pm2_setup.sh             # PM2 프로덕션 자동 가동 서비스 등록 스크립트
├── config/
│   └── global.conf          # 글로벌 스케줄러 딜레이 및 기능 플래그 설정
│   └── devices_manifest.json# 단말기 통합 메타데이터 (USB 포트, 모뎀 매핑, 스케줄 정렬, 제외 여부 통합)
├── src/
│   ├── core/
│   │   ├── scheduler.py     # 메인 루프 오케스트레이터 (동적 기동 조율)
│   │   ├── proxy_manager.py # 단말기 라이프사이클 처리기 (템플릿 주입, mitm/frida 기동)
│   │   └── gps_simulator.py # 모의 위치 인젝션 및 도착 시간 비례 동적 속도 조절기
│   ├── lib/
│   │   ├── adb.py           # ThreadPool 기반 병렬 ADB 제어 및 기기 진단 헬퍼
│   │   ├── manifest.py      # 단말기 통합 설정 메니패스트 로더/오토빌더 및 API 인터페이스
│   │   ├── check_signals.py # LTE 모뎀 신호 및 감도(RSRP/SINR) 진단 모듈
│   │   └── reporter.py      # 포스트 런 보안 오딧(익명화 검증) 및 IP 점수 갱신 모듈
│   ├── macro/
│   │   ├── executor.py      # 모바일 GUI 매크로 단계 실행기
│   │   └── ui_clicker.py    # UIAutomator XML 파싱 기반 엘리먼트 타겟 클릭커
│   ├── mitm/
│   │   ├── addon.py         # mitmproxy 메인 애드온 ( telemetry 검열 및 jitter 제어)
│   │   ├── request.py       # SSAID, ADID, IDFV 익명성 치환 및 시간 왜곡 처리
│   │   ├── response.py      # 패킷 로깅 및 캡차 타임아웃 우회 스크립트
│   │   └── whitelist.py     # 불필요한 미디어/에셋 트래픽 필터링 필터
│   └── frida/
│       ├── network_hook.js  # Java SSL Context & WebView 인증서 핀해제 훅
│       ├── core_survival.js # Android MTE 메모리 충돌 방지 및 탐지 우회 방어 훅
│       └── version_adapters/
│           ├── android_12_13.js
│           └── android_14_15.js # Conscrypt APEX 네임스페이스 메모리 오버레이 bypass
└── tools/
    ├── balance_modem_devices.sh # 1:N 단말 균등 분배 매핑 생성기
    ├── check_link_speeds.sh # 실시간 전송 속도 대시보드
    ├── check_usb_limits.sh  # PCI Host Controller 슬롯 한계 진단
    ├── clean_logs.sh        # 디스크 용량 가용율 기준 다이내믹 로그 정리 (Hourly)
    ├── fix_lte_interfaces.sh# LTE 모뎀 라우팅 폴리시 리빌더
    ├── map_usb_ports.py     # 물리 포트 매핑 디바이스 정보 조회
    └── show_session_stats.sh# 구동 세션 통계 분석 리포터
```

---

## 🚀 기동 및 사용 설명서

### 1. 호스트 서버 초기화 및 자산 다운로드
```bash
./install.sh
```
* 서버 가동에 필요한 호스트 Python 패키지(`mitmdump`, `blackboxprotobuf`, `huawei-lte-api`) 설치를 진행합니다.
* 네이버 지도 `v6.8.1.1` 에셋의 정상 유무를 점검하고 부재 시 Google Drive에서 에셋을 실시간 동기화합니다.

### 2. 생산 환경 서비스 등록 (PM2)
```bash
./pm2_setup.sh
```
* 백서버 재부팅 시에도 데몬 가동이 유지되도록 PM2 모듈에 스케줄러와 웹 모니터를 등록합니다.
* `nmap-monitor`는 자동으로 시작되며, `nmap-scheduler`는 **STOPPED** 상태로 등록되어 원할 때 켤 수 있습니다.

### 3. 스케줄러 구동
```bash
./start.sh --mode eth
```
* **eth 모드**: 4개의 물리 모뎀 대역(lte11~14)의 동적 라우팅 대역폭에 맞춰 단말을 고정 분배 구동합니다.
* **local 모드**: 가상 에뮬레이터나 일반 PC 기본 WAN 게이트웨이 환경에서 동작을 테스트할 때 사용합니다.
* **wifi 모드**: 다중 Wi-Fi 게이트웨이가 인입된 공용 무선 네트워크 모드입니다.

### 4. LTE 모뎀 신호 및 감도 진단
```bash
./start.sh --signals
```
* 각 모뎀의 활성 여부, 통신사 외부 IPv4 주소, RSRP(신호감도), SINR(신호품질) 등을 정밀 측정하여 불량 회선을 진단해 줍니다.

### 5. 멀티 디바이스 원격 제어 (CLI Broadcaster)
```bash
./cmd.sh --app-version
```
* 연결된 모든 단말기에 동시 병렬 명령을 전달하고 패키지 버전 정보를 요약 수집합니다.
* `--reboot`, `--dark`, `--light`, `--wifi <SSID> <PW>`, `--portrait` 등의 유틸리티 동작을 지원합니다.

---

## ⚠️ 프로독션 구동 시 주의사항

1. **배터리 과열 및 방전 보호 방어벽**:
   * 각 단말기의 배터리 잔량이 **20% 미만**으로 하락하거나 온도가 이상 급상승 시 기기 수명 보존을 위해 스케줄러가 해당 기기의 구동을 자동으로 보류 및 강제 종료합니다.
2. **익명화 누출 경보 (Fail-Fast Gate)**:
   * 구동 후 포스트 런 검증 과정에서 SSAID, ADID 등의 순정(Original) 값이 암호화되지 않은 평문 상태로 전송된 흔적이 발견되면 즉시 결과를 **FAIL** 처리하고 모뎀 회선을 격리합니다.
3. **네트워크 QoS 보호 (Smart Cache Preservation)**:
   * `am clear` 처리를 통해 디바이스를 씻어낼 때 지도의 오프라인 영역 에셋(`NaverNavi`, `naviguide`)과 WebView 컴파일 캐시는 임의로 제거하지 않도록 격리 처리되어 모바일 무제한 요금제 회선의 QoS 한도 제한을 방어합니다.

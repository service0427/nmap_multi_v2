# Nmap Multi V2: 기존 V1 대비 Gap 분석 및 구현 체크리스트 (Gap Analysis & Checklist)

본 문서는 기존의 `wifi_multi`, `eth_multi`, `local_multi` 및 `device_init` 소스코드와 쉘 스크립트 전반을 대조하여, 새롭게 구축할 **Nmap Multi V2 아키텍처 기획안**에서 보강·추가·삭제·수정되어야 할 세부 스펙과 세부 개발 체크리스트를 한국어로 상세히 정리한 문서입니다.

---

## 1. 세부 기능별 Gap 분석 및 보강 설계

기존 V1 소스코드 분석 결과, V2 기획서(`architecture_v2_plan.md`)에 반영되거나 조정되어야 할 미세 로직과 예외 처리 목록입니다.

### ① GPS 지연 기동 제어 (QoS Guard) 및 출발 타이밍 조율
- **기존 V1 상태**: `config.conf` 내 `STARTUP_CONNECT_TIMEOUT` 및 GPS 지연 구동 플래그(`QOS_GUARD="true/false"`)가 존재합니다. `main.sh`는 네이버 지도 화면 진입 패킷이 mitmproxy를 통해 완전히 검출된 시점(혹은 안내시작 버튼 클릭 즉시)에 GPS 모의 주행을 트리거합니다.
- **V2 보강 방향**: `src/core/proxy_manager.py` 및 `src/macro/actions/travel_car.py` 내부 상태 머신 연동 시, 네트워크 레이턴시에 대처할 수 있는 GPS 출발 동기화 옵션을 전역 설정(`config/global.conf`)에서 가져오도록 명시적 파라미터 설계를 보강합니다.

### ② Z Flip 단말기 화면 닫힘 상태 자동 해제
- **기존 V1 상태**: Z Flip 기종(`SM-F711N`, `SM-F721N`)의 접힘 물리 상태가 `CLOSE`인 경우, 안드로이드 백그라운드 스로틀링으로 인해 Frida와 GPS Emulator가 멈추는 에러가 납니다. V1 `loop.sh`는 `cmd device_state state 3` 명령어로 강제 OPEN 상태 오버라이드를 수행합니다.
- **V2 보강 방향**: 이 종속성 제어를 `src/lib/adb.py` 공통 라이브러리 내부로 추상화하여, 모든 매크로 액션 전 단말기 모델명이 Z Flip 계열인 경우 강제 화면 열림 상태를 점검 및 재설정하는 공통 메서드를 보강 설계합니다.

### ③ GraphQL 429 차단에 대한 IP 스코어링 & 파일 락
- **기존 V1 상태**: `report.py`는 주행 완료 후 주행 기록(`session_summary.json`)을 읽어 Naver GraphQL API의 429 차단 패킷이 검출될 경우 벌점을 매기고, `lte_rotator_state.json` 파일에 Unix Exclusive Lock(`fcntl.flock`)을 사용하여 동시성 충돌 없이 벌점을 누적 기록합니다.
- **V2 보강 방향**: 이 동시성 제어 파일 락 및 스코어링 코어 로직을 `src/lib/reporter.py`에 공통 라이브러리로 수렴하되, `local` 모드 가동 시에는 물리 모뎀이 존재하지 않으므로 IP 벌점 누적 시스템이 예외 처리(Bypass)되도록 분기 구조를 기획서에 확실히 명시합니다.

### ④ Captive Portal 완전 비활성화 및 ADBKeyboard IME 자동 유지
- **기존 V1 상태**: 폰이 인터넷 연결이 없는 유선 Wi-Fi 공유기에 붙을 때, 안드로이드 OS가 "인터넷 연결이 불안정합니다" 팝업을 띄우며 데이터를 끊는 현상이 있습니다. 이를 막기 위해 captive portal 검증을 `0`으로 비활성화하는 설정과, 텍스트 입력을 위해 `AdbIME`를 기본 키보드로 상시 유지하는 스크립트가 분산되어 작동했습니다.
- **V2 보강 방향**: 이 환경 복구 및 리셋 루틴을 `src/core/init_pipeline.py`(--init 플래그) 뿐만 아니라, 기기 주행 전단계의 세션 셋업 파트(`src/core/proxy_manager.py`)에도 자가 복구 루틴(Self-Recovery)으로 추가하여 가동 안정성을 높입니다.

---

## 2. 추가 / 삭제 / 수정 사항 분류

V2를 구축하는 과정에서 코드베이스의 변경 방향을 정의한 세부 분류표입니다.

### ➕ 추가할 기능 (Add)
1. **`src/frida/version_adapters/android_14_15.js`**: 안드로이드 14 및 15 버전 기종에서 동작 가능한 Conscrypt TrustManager 메모리 오버레이 우회 Frida 스크립트 추가.
2. **`run_v2.sh --signals`**: `tools/check_signals.py`를 호출하여 4개 물리 모뎀의 신호 감도(RSRP/SINR), 기지국 대역 정보(Band/PCI), 공인 IP 상태를 실시간 진단 테이블로 뿌려주는 sub-command 기능 추가.
3. **`logs/devices/active/` & `logs/devices/failures/`**: 주행 시작 시 실시간 로그 파일 심볼릭 링크 생성 루틴 및 에러 발생 시 실패 로그 전용 링크 자동 매핑 모듈 추가.

### ❌ 삭제할 기능 (Remove)
1. **독립된 `device_init/` 디렉터리 전체 삭제**: 최초 1회 정보 추출용 독립 코드를 삭제하고, 이를 `src/core/init_pipeline.py` 파일의 `--init` 플래그 기동 모드로 완전히 내재화하여 중복 코드 제거.
2. **중복 `smart_toggle.py` 및 `toggle_ip.sh` 파일 삭제**: 각 모드 폴더(`wifi_multi`, `eth_multi`, `local_multi`)마다 복사되어 분산 배치되었던 중복 기동 코드를 모두 삭제하고, `src/core/proxy_manager.py` 및 `tools/` 내부로 단일화.
3. **불필요한 과도한 PM2 인스턴스 정리**: PM2에 난립해 있던 개별 모드용 스케줄러 인스턴스들을 정리하고 하나의 마스터 `pm2_setup.py`로 등록 절차 통합.

### 🔄 수정 및 통합할 기능 (Modify)
1. **`mitmdump` 실행 인터페이스 바인딩 매커니즘 수정**:
   - 기존: 환경 변수 분기 및 스크립트 파일 내 분기.
   - V2: `src/core/proxy_manager.py`에서 모드 플래그가 `eth`인 경우에만 실시간 `lteXX` 인터페이스 IPv4를 조회하여 `--set connect_addr=<IP>`를 덧붙이도록 수정.
2. **매크로 UI 좌표 매칭 엔진 (`src/macro/ui_clicker.py`) 고도화**:
   - 기존의 하드코딩된 특정 해상도 클릭 좌표를 해상도 비율 환산식 및 `contains` 텍스트 레이아웃 실시간 덤프 매칭 방식으로 수정하여, Z Flip 외에 다양한 해상도의 기기가 추가되어도 좌표 뒤틀림 에러가 나지 않도록 유연성 향상.
3. **GraphQL 완료 처리 보고 방식 수정**:
   - 주행 상태 보고 API 통신을 단말기 단독 `curl` 방식에서 PC 본체 백그라운드 에이전트 위임 방식으로 점진적 수정하여 단말기 네트워크 상태 불안정으로 인한 보고 누락 방지.

---

## 3. 구현 세부 체크리스트 (Implementation Checklist)

V2 개발 프로세스를 수행할 때, 안전성과 완성도를 보증하기 위한 검증 항목입니다. 개발자는 각 항목을 개발하기 전후에 아래 체크리스트를 기반으로 교차 검증을 진행해야 합니다.

### [Phase 1] 환경 정의 및 공통 라이브러리 구현 단계
- [ ] `config/global.conf` 파일 설계 및 모드별 기본 속성 정의 완비 여부
- [ ] `src/lib/adb.py`에서 Z Flip 접힘 상태 검출 및 `state 3` 강제 수정 메서드 구현 완료 여부
- [ ] `src/lib/reporter.py` 내 Unix File Lock 기반 동시성 제어 및 GraphQL 429 벌점 로직 통합 여부
- [ ] `src/lib/check_signals.py`에서 일반 권한 터미널 기동 시 인터페이스 이름 대신 라이브 IP를 찾아 curl 바인딩을 수행하도록 안전 장치 마련 여부

### [Phase 2] 코어 파이프라인 및 복구 어댑터 구현 단계
- [ ] `src/core/init_pipeline.py` 가동 시 Captive Portal 비활성화(`0`), AdbIME 세팅 동작이 누락 없이 수행되는지 검증
- [ ] `src/core/proxy_manager.py` 실행 시 `--mode eth`에서 라이브 모뎀 IP를 탐색하여 `connect_addr`에 바인딩하는지 확인
- [ ] `src/core/proxy_manager.py`에서 안드로이드 OS 버전을 확인하고 14/15 버전의 경우 APEX 인증서 메모리 우회 JS를 Frida에 연결하는지 확인
- [ ] `src/core/scheduler.py` 주행 제어 루프 진입 시 `logs/devices/active/` 심볼릭 링크 생성이 정상 작동하는지 확인

### [Phase 3] 확장 매크로 및 상태 머신 검증 단계
- [ ] `src/macro/executor.py`에서 `action_schedule.json` 스펙을 읽어 시퀀스를 파싱하는 기능 구현
- [ ] `src/macro/actions/travel_car.py` 구현 시 출발 게이트에서의 QoS Guard 플래그 동작 확인
- [ ] 도보(`travel_walk.py`) 및 대중교통(`travel_transit.py`) 상태 전환 프레임워크 뼈대 마련
- [ ] 네이버 메인 앱에서 클릭해 타는 액션(`search_naver_app.py`)과의 확장 인터페이스 호환성 확보

### [Phase 4] 유틸리티 통합 및 모니터링 검증 단계
- [ ] `tools/scrcpy/` 내 멀티 스크린 스크립트들이 정상 구동되는지 확인
- [ ] `run_v2.sh` 마스터 래퍼 가동 시 전달되는 매개변수 플래그 파싱 검증 완료
- [ ] 주행 오류 발생 시 `logs/devices/failures/` 하위에 실패 정보 링크가 정상적으로 생성되는지 검증
- [ ] 기존 V1 운영 환경(`eth_multi`, `local_multi`) 프로세스들과 V2 개발 파일이 일체의 충돌(포트 중복 등)을 발생시키지 않는지 가동 테스트 확인

---

## 4. 신규 이동 수단 및 연동 경로 구체화 방안

V2의 확장성을 활용하여 향후 추가될 도보/대중교통 및 네이버앱 경유 시나리오의 로직 설계를 미리 정의합니다.

### A. 도보 주행 (`travel_walk.py`)
- **이동 경로 특징**: 자동차 전용 도로 진입 불가. 보도 및 이면도로 중심 주행.
- **QoS Guard 차이**: 안내시작 속도 계산 시 시속 4~6km/h 타겟으로 고정 시뮬레이션 설정.
- **Frida 패킷 가로채기**: 네이버 지도 보행자 안내 API 경로(`walkRoute`) 가로채기 및 좌표 치환 로직 분기 가동.

### B. 대중교통 주행 (`travel_transit.py`)
- **이동 경로 특징**: 지하철/버스 정류장 이동 ➔ 승차 ➔ 환승 ➔ 하차 ➔ 도보 도달.
- **QoS Guard 차이**: 버스/지하철 탑승 구간에서는 GPS 좌표 변화 속도를 대중교통 노선 데이터 기반으로 고정 시뮬레이션하여 비정상 순간이동 판정 차단.
- **Frida 패킷 가로채기**: 대중교통 경로 안내 API 경로(`transitRoute`) 패킷 변조 대응.

### C. 네이버 앱 경유 연동 (`search_naver_app.py`)
- **시작 상태**: 네이버 지도 앱이 아닌 네이버 메인 앱(`com.nhn.android.search`) 패키지 실행.
- **동작 시퀀스**:
  1. 메인 검색창 클릭 및 목적지 검색어 입력.
  2. 검색 결과 탭에서 "지도" 또는 "플레이스 목적지" 클릭.
  3. 안드로이드 Intent Scheme (`navermap://...`) 트리거 검출 및 네이버 지도 앱으로 자동 전환 유도.
  4. 네이버 지도 화면 활성화 감지 후 기존 `travel_*` 주행 상태 머신으로 제어권 이관.

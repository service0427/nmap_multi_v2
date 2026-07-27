# Nmap Multi V2: 기존 V1 전수 파일 진단 및 재조정 기획안 (Exhaustive File Audit & Reorganization Plan)

본 문서는 기존 V1 프로젝트 루트(`/home/tech/nmap_multi_v1/`) 및 하위 디렉터리에 존재하는 모든 파일들의 역할을 정밀 진단하고, V2 통합 프로젝트(`/home/tech/nmap_multi_v2/`)로 마이그레이션할 때의 **추가·삭제·이동·이름 변경 및 통합 계획**을 파일 단위로 상세히 정의한 문서입니다.

---

## 1. 루트 디렉터리 파일 진단 및 이동 계획 (Refined)

루트 디렉터리를 가볍게 비우고, 자주 사용하며 통합된 3개의 스크립트(`start.sh`, `install.sh`, `cmd.sh`)만 유지합니다. 파일명 내의 버전 번호(예: `_v2`)는 제외합니다.

| 기존 V1 파일명 | 파일 역할 기술 | 진단 결과 및 중복 여부 | V2 재배치 및 파일명 수정 계획 |
| :--- | :--- | :--- | :--- |
| `check_signals.sh` | 모뎀 감도를 측정하는 파이썬 래퍼 쉘 | 단순 래퍼 | **삭제 후 통합**: `start.sh --signals` 플래그 명령으로 내재화 |
| `check_speeds.sh` | 모뎀의 다운로드/업로드 속도를 측정하는 스크립트 | 유틸리티 | **이동 & 이름 변경**: `tools/check_link_speeds.sh` |
| `repair_environment.sh` | 패키지 의존성 및 모뎀/단말기 환경 복구 | 핵심 진단 유틸 | **이동 & 이름 변경**: `tools/repair_system_env.sh` |
| `mitm_recovery.sh` | mitmproxy 충돌 시 포트 해제 및 프로세스 킬 | 예외 복구 유틸 | **이동 & 이름 변경**: `tools/recover_mitmproxy.sh` |
| `recovery_device.sh` | 특정 단말기 먹통 시 adb 재부팅 및 복구 | 단말기 복구 유틸 | **통합 후 삭제**: `cmd.sh --reboot <serial>` 또는 `src/lib/adb.py`에서 처리 |
| `get_devices.sh` | 연결된 기기 리스트 및 상태를 조회 | 단순 모니터링 툴 | **삭제 후 통합**: `src/lib/adb.py` 및 `start.sh --devices` 명령으로 내재화 |
| `eth_get_devices.sh` | 1:N 로드밸런싱 맵핑을 생성하는 신규 툴 | 핵심 동기화 유틸 | **이동 & 이름 변경**: `tools/balance_modem_devices.sh` |
| `map_usb_devices.py` | USB 허브 포트와 단말기 시리얼 매칭 | 하드웨어 맵핑 툴 | **이동 & 이름 변경**: `tools/map_usb_ports.py` |
| `check_usb_limits.sh` | USB 대역폭 및 전류 부하 검사 | 대규모 단말기 관리용 | **이동 & 이름 변경**: `tools/check_usb_limits.sh` |
| `fix_eth_number.sh` | lte 인터페이스 순서 보정 및 PBR 재생성 | 네트워크 복구 툴 | **이동 & 이름 변경**: `tools/fix_lte_interfaces.sh` |
| `log_clean.sh` | 주기적으로 오래된 로그를 삭제하는 크론 스크립트 | 로그 유틸 | **이동 & 이름 변경**: `tools/clean_logs.sh` |
| `sync_lte.sh` | lte 모뎀의 시간/상태 강제 동기화 | 모뎀 유틸 | **이동 & 이름 변경**: `tools/sync_modems.sh` |
| `install_lte_multi.sh` | 화웨이 드라이버 및 PBR 바인딩 최초 설치 스크립트 | 서버 셋업용 | **통합 및 내재화**: 루트의 `install.sh --server`로 통합 |
| `install_cli_os.sh` | 단말기 커스텀 OS 및 패키지 초기 설치 배치 스크립트 | 기기 셋업용 | **통합 및 내재화**: 루트의 `install.sh --phone`으로 통합 |
| `update_nmap.sh` | 구글 드라이브에서 지도 패키지를 받아 갱신하는 파일 | 에셋 유틸 | **통합 및 내재화**: 루트의 `install.sh --download`로 통합 |
| `update_nmap_drive.sh` | 구글 드라이브 업로더 및 깃 푸시 자동화 스크립트 | 원격 동기화 유틸 | **이동 & 이름 변경**: `tools/sync_nmap_drive.sh` |
| `device_init.sh` | 기기 정보 추출 및 AdbIME 세팅 스크립트 | 최초 기기 셋업용 | **삭제 후 통합**: `src/core/init_pipeline.py` 코어로 100% 이관 및 통합 |
| `show_stats.sh` | 실시간 주행 카운트 및 완료 건수 집계 래퍼 | 리포트 툴 | **이동 & 이름 변경**: `tools/show_session_stats.sh` |
| `cmd.sh` | 60대 단말기에 adb 명령어를 동시 전송하는 다중 실행기 | 다중 제어 툴 | **보존 및 고도화**: 루트의 **`cmd.sh`**로 통합 및 리팩토링 |
| `version.conf` | 타겟 네이버 지도 버전 및 드라이브 ID 환경 설정 파일 | 설정 파일 | **이동**: `config/version.conf` |
| `pm2_setup.sh` | 기존 루트의 PM2 일괄 등록 스크립트 | 등록 유틸 | **삭제 후 통합**: `install.sh --server` 내 등록 스펙 및 `src/core/pm2_setup.py`로 고도화 |

---

## 2. `cmd/` 및 `utils/` 주요 파일 진단 및 재배치 (중복 ADB 파일 제거 및 cmd.sh 통폐합)

단말기 원격 제어 파일들은 개별 파일로 만들지 않고, **루트의 `cmd.sh` 및 공통 모듈인 `src/lib/adb.py` 내부의 병렬 처리기(Concurrency Executor)로 흡수**시킵니다. 이로써 단말기를 순회하며 adb 명령어를 실행하던 중복 코드들이 완벽하게 단일화됩니다.

| 기존 V1 파일 경로 | 파일 역할 기술 | V2 재배치 및 통합 계획 |
| :--- | :--- | :--- |
| `utils/web_monitor.py` | Flask 실시간 단말기 관제 및 모니터링 웹 대시보드 | **이동 & 상시 기동**: `src/core/web_monitor.py`로 상시 가동 설정 |
| `cmd/wifi.sh` | 60대 단말기의 Wi-Fi 프로필 삭제 및 SSID 연결 | **삭제 후 통합**: 루트의 `cmd.sh --wifi`로 통합 관리 |
| `cmd/reboot.sh` | 60대 단말기를 순차적으로 백그라운드 재부팅 | **삭제 후 통합**: 루트의 `cmd.sh --reboot`로 통합 관리 |
| `cmd/home.sh` | 60대 단말기에 HOME 키 이벤트 전송 | **삭제 후 통합**: 루트의 `cmd.sh "keyevent 3"`으로 병합 |
| `cmd/dark.sh` | 60대 단말기 다크모드 강제 적용 | **삭제 후 통합**: 루트의 `cmd.sh --dark`로 통합 관리 |
| `cmd/light.sh` | 60대 단말기 라이트모드 강제 적용 | **삭제 후 통합**: 루트의 `cmd.sh --light`로 통합 관리 |
| `cmd/portrait.sh` | 60대 단말기의 화면 회전을 세로 모드로 잠금 | **삭제 후 통합**: 루트의 `cmd.sh --portrait`로 통합 관리 |
| `cmd/emergency.sh` | 비상 상황 시 가동 프로세스 일시 정지 및 안전 귀가 | **삭제 후 통합**: 루트의 `cmd.sh --emergency`로 통합 관리 |
| `cmd/check_nmap_version.sh`| 60대 단말기의 네이버 지도 버전 체크 | **삭제 후 통합**: 루트의 `cmd.sh --app-version`으로 통합 관리 |
| `cmd/patch_naver_map.sh` | 루팅 권한을 이용해 네이버 지도 보안 패치 | **삭제 후 통합**: 루트의 `cmd.sh --patch-app`으로 통합 관리 |
| `cmd/exit_usim.sh` | USIM 캐리어 강제 접속 종료 유도 | **삭제 후 통합**: 루트의 `cmd.sh --disable-usim`으로 통합 관리 |
| `cmd/ip.sh` | 60대 단말기의 Wi-Fi IP 할당 상태 일괄 체크 | **삭제 후 통합**: 루트의 `cmd.sh --wifi-ips`로 통합 관리 |

---

## 3. 용도별 중복 디렉터리 (`wifi_multi`, `eth_multi`, `local_multi`) 통폐합 계획

중복되던 모듈 코어 파일들을 V2 코어로 완전 병합합니다.

- **` smart_toggle.py` 및 `toggle_ip.sh`** ➔ **`src/core/modem_rotator.py`**로 병합.
- **`daily_report.sh` 및 `macro/daily_report.py`** ➔ **`src/lib/reporter.py`** 및 **`src/macro/daily_report_agent.py`**로 통합.
- **Frida JS 파일 3종** ➔ **`src/frida/network_hook.js`**, **`src/frida/core_survival.js`**로 일원화.
- **GPS 프리퍼런스 빌더 3종** ➔ **`src/core/gps_simulator.py`**로 병합.

---

## 4. V2 폴더 마이그레이션 및 네임스페이스 매핑 테이블

이전 버전의 파일을 V2에 배치하기 위한 최종적인 매핑 매트릭스입니다.

```text
기존 V1 파일 경로                             ➔   V2 대상 파일 경로 (Refined - No Version Suffix)
----------------------------------------------------------------------------------------------------
/run_v2.sh                                    ➔   /start.sh (통합 CLI 래퍼)
/install_lte_multi.sh                         ➔   /install.sh --server (통합)
/install_cli_os.sh                            ➔   /install.sh --phone (통합)
/update_nmap.sh                               ➔   /install.sh --download (통합)
/cmd.sh                                       ➔   /cmd.sh (통합 원격 래퍼 - wifi/reboot/ip/usim/patch 통합)
/utils/web_monitor.py                         ➔   /src/core/web_monitor.py (상시 가동 모니터)

[tools/ 디렉터리 스크립트]
/check_speeds.sh                              ➔   /tools/check_link_speeds.sh
/repair_environment.sh                        ➔   /tools/repair_system_env.sh
/mitm_recovery.sh                             ➔   /tools/recover_mitmproxy.sh
/eth_get_devices.sh                           ➔   /tools/balance_modem_devices.sh
/map_usb_devices.py                           ➔   /tools/map_usb_ports.py
/check_usb_limits.sh                          ➔   /tools/check_usb_limits.sh
/fix_eth_number.sh                            ➔   /tools/fix_lte_interfaces.sh
/log_clean.sh                                 ➔   /tools/clean_logs.sh
/sync_lte.sh                                  ➔   /tools/sync_modems.sh
/update_nmap_drive.sh                         ➔   /tools/sync_nmap_drive.sh
/show_stats.sh                                ➔   /tools/show_session_stats.sh

[wifi_multi/eth_multi/local_multi 공통 통합]
/*/smart_toggle.py                            ➔   /src/core/modem_rotator.py
/*/lib/report.py                              ➔   /src/lib/reporter.py
/*/lib/main.sh                                ➔   /src/core/proxy_manager.py
/*/loop.sh                                    ➔   /src/core/scheduler.py
/*/gps/static.sh                              ➔   /src/core/gps_simulator.py
/*/gps/auto_reloader.py                       ➔   /src/core/gps_simulator.py
/*/mitm/addon.py                              ➔   /src/mitm/addon.py
/*/mitm/whitelist.py                          ➔   /src/mitm/whitelist.py
/*/lib/hooks/network_hook.js                  ➔   /src/frida/network_hook.js
/*/lib/hooks/_core_survival.js                ➔   /src/frida/core_survival.js
/*/macro/ui_clicker.py                        ➔   /src/macro/ui_clicker.py
/*/macro/daily_report.py                      ➔   /src/macro/daily_report_agent.py
```

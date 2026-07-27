# Nmap Multi V2: Master Handover Documentation & Initial Prompt Guide
> **Document Version**: 2.0 (Standalone Clean Migration Complete)
> **Root Directory**: `/home/tech/nmap_multi_v2`
> **GitHub Repository**: `https://github.com/service0427/nmap_multi_v2`

---

## 1. Project Overview & Current Infrastructure

This project is **Nmap Multi V2**, an enterprise multi-device Android automation, GQL telemetry spoofing, and real-time driving simulation system managing **60 Samsung Galaxy Z Flip 3 smartphones**.

### 🌐 System Network & Server Endpoints (Tailscale Subnet)
* **Server Tailscale Fixed IP**: `100.97.230.66`
* **Central API Server (Tailscale IP)**: `http://100.65.34.98:8013` (Speed: `7.97ms` - 100% parity with public IP)
* **Dev Control AG-Grid Dashboard**: `http://100.97.230.66:5001/` (Unified AG Grid + Screen Inspection Modal)
* **Dev Control REST API**: `http://100.97.230.66:5555/api/v1/devices`
* **Scrcpy Touch Mirroring Server**: `http://100.97.230.66:5000/`

---

## 2. Key Technical Accomplishments & System State

### 🛡️ 1. Complete Standalone Relocation & GitHub Backup
* Moved from old `/home/tech/nmap_multi_v1/nmap_multi_v2` to standalone root **`/home/tech/nmap_multi_v2`**.
* Pushed 100% clean codebase to GitHub repository: `https://github.com/service0427/nmap_multi_v2.git`.
* Zero external runtime dependencies on V1.

### 🔇 2. Hardware-Level Audio Alert Bypass & Complete Mute (Do Not Disturb)
* Resolved issue where speed camera alert sounds bypassed media volume 0 (`USAGE_ASSISTANCE_SONIFICATION`, `flags=0x800`).
* Configured `settings put global zen_mode 2` (Total Silence DND) and `cmd notification set_dnd on` in `proxy_manager.py` (L336-L338) across all 58 physical devices.

### 📊 3. Dev Control AG-Grid Hub (Port 5001 & Port 5555)
* **AG Grid v31.3.2 Integration**: Pixel-perfect dark quartz theme with column sorting, quick search filtering, and pinned columns.
* **Korean Pretendard Typography**: High-contrast, clean Pretendard Korean web font.
* **1-Click Screen Inspection**: `[📺 화면보기]` button opens enlarged 1.5s live screen stream with direct link to `http://100.97.230.66:5000/` Scrcpy touch mirroring.
* **Granular Controls**: Icon buttons per device:
  * `🔄` (Restart): 1s instant map force-stop, ADBKeyboard check, and task re-allocation.
  * `🛑` (Force Stop): Kills proxy/GPS/frida subprocesses and reports `FAIL (MANUAL_STOP)`.
  * `⏸` (Hold Next Session): Finishes current session cleanly, then holds in `PAUSED` state without fetching new tasks.
  * `▶` (Resume): Resumes taking tasks immediately.

### ⚡ 4. Async Worker Pool Migration (`scheduler_async.py`) & Modernized CLI (`start.sh`)
* **64 Parallel Worker Threads**: Replaced the legacy single-thread linear loop in `scheduler.py` with `scheduler_async.py`, eliminating the 5-minute loop bottleneck and enabling zero-delay (<0.1s) device task pickup.
* **LTE Subnet Staggering Retained**: `SubnetLock` ensures devices sharing the same LTE modem stagger GQL requests while devices across different modems run with 0 latency.
* **Unified CLI Control (`start.sh`)**: Added direct flag support for device actions (`./start.sh --device R5CR80ZNCXT --action restart`) and mode selection (`--mode eth`, `--legacy-mode eth`).

---

## 3. PM2 Process Map (`pm2 list`)

| ID | Process Name | Command / Script | Port / Description |
| :--- | :--- | :--- | :--- |
| `1` | **nmap-scheduler** | `./start.sh --mode eth` | Central Async Parallel Task Scheduler |
| `0` | **nmap-monitor** | `tools/scrcpy/sync_gui_control.py` | Port 5000 Scrcpy Touch Mirroring |
| `6` | **nmap-dev-api** | `dev_control/api/server.py` | Port 5555 Dev REST API Engine |
| `7` | **nmap-dev-web** | `dev_control/web/app.py` | Port 5001 AG-Grid Dev Web Hub |
| `3` | **adb-recovery-monitor** | `tools/adb_recovery_monitor.py` | ADB Device Health Auto-Recovery |
| `4` | **lte-usage-sender** | `tools/sync_modems.py --daemon` | LTE Data Usage Reporting Daemon |
| `5` | **lte-ip-rotator** | `tools/lte_ip_rotator.py` | LTE Modem Subnet IP Rotation Daemon |
| `2` | **nmap-log-cleaner** | `tools/clean_logs.sh` | Hourly Log Purge (Cron) |

---

## 4. System Maintenance & Operational Commands

1. **Launch Async Parallel Scheduler**: `./start.sh --mode eth`
2. **Execute Single Device Control Action**: `./start.sh --device <DEVICE_ID> --action <restart|stop|pause|start|mute|clear_cooldown>`
3. **Display LTE Modem Signals**: `./start.sh --signals`

---

## 🤖 INITIAL PROMPT FOR NEW CHAT SESSION (새 대화 시작 시 사용할 복사용 프롬프트)

When starting a new conversation, copy and paste the following prompt:

```text
안녕하세요! nmap_multi_v2 프로젝트의 다음 개발 작업을 이어 진행하고자 합니다.

[프로젝트 기본 정보 및 상태]
1. 프로젝트 루트 경로: /home/tech/nmap_multi_v2
2. GitHub 저장소: https://github.com/service0427/nmap_multi_v2
3. 대시보드 및 API 서버 주소 (Tailscale):
   - Dev AG-Grid 관제 웹 (Port 5001): http://100.97.230.66:5001/
   - Dev 관제 REST API (Port 5555): http://100.97.230.66:5555/api/v1/devices
   - Scrcpy 터치 미러링 (Port 5000): http://100.97.230.66:5000/
   - 중앙 API 서버 (Tailscale): http://100.65.34.98:8013
4. 핸드오버 문서 참조: /home/tech/nmap_multi_v2/HANDOVER.md (또는 아티팩트 v2_handover_documentation.md)

이전 대화에서 완료된 핵심 작업(AG-Grid 통합 대시보드, zen_mode 2 하드웨어 방해금지 무음, Tailscale IP 전환, /home/tech/nmap_multi_v2 독립 마이그레이션 및 GitHub 백업)을 바탕으로 다음 고도화 작업을 시작하겠습니다.
```

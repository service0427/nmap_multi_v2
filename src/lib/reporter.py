#!/usr/bin/env python3
import os
import sys
import json
import glob
import re
import fcntl
from datetime import datetime

class IdentityAuditEngine:
    @staticmethod
    def audit_and_score(log_dir, device_id, task_id, reason):
        # 1. Load original & spoofed pairs from environment
        pairs = {
            "ssaid": (os.environ.get("NMAP_ORIG_SSAID"), os.environ.get("NMAP_ID_SSAID")),
            "adid": (os.environ.get("NMAP_ORIG_ADID"), os.environ.get("NMAP_ID_ADID")),
            "idfv": (os.environ.get("NMAP_ORIG_IDFV"), os.environ.get("NMAP_ID_IDFV")),
            "ni": (os.environ.get("NMAP_ORIG_NI"), os.environ.get("NMAP_ID_NI")),
            "token": (os.environ.get("NMAP_ORIG_TOKEN"), os.environ.get("NMAP_ID_TOKEN")),
        }
        
        # 2. Scan packets for leak detection
        actual_replacements = {}
        ignore_files = {"api_response.json", "session_summary.json", "execution.log", "report.json", "result.json", "events.log"}
        target_files = []
        for root, _, files in os.walk(log_dir):
            for f in files:
                if f not in ignore_files and (f.endswith(".json") or f.endswith(".jsonl") or f.endswith(".log")):
                    target_files.append(os.path.join(root, f))
                    
        all_content = ""
        for fpath in target_files:
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    if fpath.endswith(".json"):
                        try:
                            obj = json.loads(content)
                            def clean_original_logs(item):
                                if isinstance(item, dict):
                                    for k in list(item.keys()):
                                        if k.startswith("original_") or k == "_raw":
                                            item.pop(k)
                                        else:
                                            clean_original_logs(item[k])
                                elif isinstance(item, list):
                                    for x in item:
                                        clean_original_logs(x)
                            clean_original_logs(obj)
                            content = json.dumps(obj)
                        except:
                            pass
                    all_content += content + "\n"
            except:
                pass
            
        leak_detected = False
        leak_msg_list = []
        
        for key, (orig, spoof) in pairs.items():
            orig_count = 0
            spoof_count = 0
            if orig and len(orig) > 5:
                orig_count = all_content.lower().count(orig.lower())
            if spoof and len(spoof) > 5:
                spoof_count = all_content.lower().count(spoof.lower())
                
            status = "NOT_TRANSMITTED"
            if orig_count > 0:
                status = "FAILED_LEAKED"
                leak_detected = True
                leak_msg_list.append(f"{key} leaked {orig_count} times")
            elif spoof_count > 0:
                status = "SUCCESSFULLY_REPLACED"
                
            actual_replacements[key] = {
                "status": status,
                "original_value": orig,
                "spoofed_value": spoof,
                "original_found_count": orig_count,
                "spoofed_found_count": spoof_count
            }
            
        # 3. Parse captured cookies from v2_tokens.json
        cookie_data = {"NAPP_DI": None, "NAC": None, "NNB": None, "BUC": None, "NSCS": None}
        token_files = glob.glob(os.path.join(log_dir, "**/*_POST_v2_tokens.json"), recursive=True)
        if token_files:
            token_files.sort(reverse=True)
            try:
                with open(token_files[0], "r", encoding="utf-8", errors="ignore") as f:
                    t_json = json.load(f)
                    cookie_str = t_json.get("request", {}).get("headers", {}).get("cookie", "")
                    if cookie_str:
                        for k in cookie_data.keys():
                            m = re.search(rf"{k}=([^,; ]+)", cookie_str)
                            if m:
                                cookie_data[k] = m.group(1)
            except:
                pass
                
        # 4. Save report.json
        leak_msg = "; ".join(leak_msg_list)
        report = {
            "task_metadata": {
                "task_id": int(task_id) if str(task_id).isdigit() else task_id,
                "device_id": device_id,
                "termination_reason": reason,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            },
            "security_audit": {
                "leak_status": "LEAK_DETECTED" if leak_detected else "CLEAN",
                "leak_message": leak_msg
            },
            "identity_spoofing_audit": actual_replacements,
            "actual_captured_cookies": cookie_data
        }
        
        report_path = os.path.join(log_dir, "report.json")
        with open(report_path, "w", encoding="utf-8") as rf:
            json.dump(report, rf, indent=2, ensure_ascii=False)
        print(f"[✓] report.json generated. Leak Status: {report['security_audit']['leak_status']}")

        # 4.5 Save persistent session run results to CSV (Used by stats dashboard)
        history_csv = "/home/tech/nmap_multi_v2/logs/rotator_history/session_history.csv"
        os.makedirs(os.path.dirname(history_csv), exist_ok=True)
        try:
            write_header = not os.path.exists(history_csv)
            with open(history_csv, "a", encoding="utf-8") as hf:
                fcntl.flock(hf, fcntl.LOCK_EX)
                if write_header:
                    hf.write("Timestamp,DeviceID,Subnet,TaskID,Status,Message\n")
                
                ts_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                clean_reason = str(reason).replace("\n", " ").replace(",", ";")
                status_csv = "SUCCESS" if reason == "Task Completed" else "FAIL"
                
                # Retrieve bind_ip from environment or scan exec_log
                bind_ip_val = "0"
                exec_log_path = os.path.join(log_dir, "execution.log")
                if os.path.exists(exec_log_path):
                    with open(exec_log_path, 'r', encoding='utf-8', errors='ignore') as ef:
                        exec_content = ef.read()
                        bind_match = re.search(r'BIND_IP:([0-9\.]+)', exec_content)
                        if bind_match:
                            bind_ip_val = bind_match.group(1)
                
                sub_num = "0"
                if bind_ip_val != "0":
                    parts = bind_ip_val.split('.')
                    if len(parts) >= 3:
                        sub_num = parts[2]
                
                hf.write(f"{ts_now},{device_id},{sub_num},{task_id},{status_csv},{clean_reason}\n")
        except Exception as e:
            print(f"[-] Error writing CSV history: {e}")

        # 5. IP Scoring
        try:
            real_ip = "UNKNOWN"
            bind_ip = "UNKNOWN"
            summary_data = None
            
            summary_path = os.path.join(log_dir, "session_summary.json")
            if os.path.exists(summary_path):
                with open(summary_path, 'r', encoding='utf-8', errors='ignore') as sf:
                    summary_data = json.load(sf)
                    real_ip = summary_data.get("real_ip", "UNKNOWN")
            
            exec_log_path = os.path.join(log_dir, "execution.log")
            if os.path.exists(exec_log_path):
                with open(exec_log_path, 'r', encoding='utf-8', errors='ignore') as ef:
                    exec_content = ef.read()
                    if real_ip == "UNKNOWN":
                        ip_match = re.search(r'Real IPv4:\s*([0-9\.]+)', exec_content)
                        if ip_match:
                            real_ip = ip_match.group(1)
                    bind_match = re.search(r'BIND_IP:([0-9\.]+)', exec_content)
                    if bind_match:
                        bind_ip = bind_match.group(1)
            
            has_real_error_log = False
            has_access_log = False
            error_log_files = glob.glob(os.path.join(log_dir, "**/*_POST_client-logger_errorLog.json"), recursive=True)
            for ef in error_log_files:
                try:
                    with open(ef, 'r', encoding='utf-8', errors='ignore') as f:
                        data = json.load(f)
                        if data.get("url") == "https://ncpt.naver.com/client-logger/errorLog":
                            body = data.get("request", {}).get("body", {})
                            if isinstance(body, dict) and body.get("message"):
                                has_real_error_log = True
                                break
                except: pass

            access_log_files = glob.glob(os.path.join(log_dir, "**/*_POST_client-logger_accessLog.json"), recursive=True)
            for af in access_log_files:
                try:
                    with open(af, 'r', encoding='utf-8', errors='ignore') as f:
                        data = json.load(f)
                        if data.get("url") == "https://ncpt.naver.com/client-logger/accessLog":
                            has_access_log = True
                            break
                except: pass

            # Determine modem name
            modem_name = None
            if bind_ip != "UNKNOWN":
                parts = bind_ip.split('.')
                if len(parts) >= 3:
                    subnet_num = parts[2]
                    if subnet_num.isdigit() and 11 <= int(subnet_num) <= 20:
                        modem_name = f"lte{subnet_num}"

            # If no physical modem (like local mode)
            if bind_ip.startswith("192.168.11.") or modem_name:
                state_file = "/home/tech/nmap_multi_v2/logs/lte_rotator_state.json"
                os.makedirs(os.path.dirname(state_file), exist_ok=True)
                
                if not os.path.exists(state_file):
                    with open(state_file, 'w', encoding='utf-8') as f:
                        json.dump({}, f)
                        
                with open(state_file, 'r+', encoding='utf-8') as s_f:
                    fcntl.flock(s_f, fcntl.LOCK_EX)
                    try:
                        state_data = json.load(s_f)
                    except:
                        state_data = {}
                        
                    lte_keys = []
                    try:
                        for name in os.listdir('/sys/class/net'):
                            if name.startswith("lte"):
                                lte_keys.append(name)
                    except: pass
                    
                    def extract_num(s):
                        m = re.search(r'\d+', s)
                        return int(m.group(0)) if m else 0
                    lte_keys = sorted(list(set(lte_keys)), key=extract_num)
                    
                    for k in state_data.keys():
                        if k.startswith("lte") and k not in lte_keys:
                            lte_keys.append(k)
                    lte_keys = sorted(lte_keys, key=extract_num)
                    
                    if not lte_keys:
                        lte_keys = [f"lte{i}" for i in range(11, 21)]
                        
                    for key in lte_keys:
                        if key not in state_data:
                            state_data[key] = {}
                        if isinstance(state_data[key], (int, float)):
                            state_data[key] = {
                                "next_scheduled_rotation": "",
                                "last_toggle": "",
                                "current_ip": "UNKNOWN",
                                "ip_score": 0,
                                "last_score_update": ""
                            }
                        state_data[key].setdefault("next_scheduled_rotation", "")
                        state_data[key].setdefault("last_toggle", "")
                        state_data[key].setdefault("current_ip", "UNKNOWN")
                        state_data[key].setdefault("ip_score", 0)
                        state_data[key].setdefault("last_score_update", "")
                        
                    if not modem_name and real_ip != "UNKNOWN":
                        for name, details in state_data.items():
                            if isinstance(details, dict) and details.get("current_ip") == real_ip:
                                modem_name = name
                                break
                                
                    if modem_name and modem_name in state_data:
                        details = state_data[modem_name]
                        registered_ip = details.get("current_ip", "UNKNOWN")
                        
                        if registered_ip != "UNKNOWN" and real_ip != "UNKNOWN" and registered_ip != real_ip:
                            print(f"[⚪ IP SCORING] Skipped score update: Session IP {real_ip} does not match current registered IP {registered_ip} on {modem_name}")
                        else:
                            curr_score = details.get("ip_score", 0)
                            graphql_429_count = 0
                            if summary_data and isinstance(summary_data, dict):
                                for pkt in summary_data.get("packets", []):
                                    if "graphql" in pkt.get("path", "") and pkt.get("status") == 429:
                                        graphql_429_count += 1
                                        
                            change_amount = 0
                            event_type = "NEUTRAL"
                            is_gql_429 = (graphql_429_count > 0 or "GQL_429" in str(reason))
                            
                            # 점수는 routeend 완료 (Task Completed) 시에만 채점합니다.
                            if reason == "Task Completed":
                                if is_gql_429:
                                    score_to_add = 1  # 429가 여러번 발생하더라도 세션당 1회 +1점
                                    new_score = min(100, curr_score + score_to_add)
                                    change_amount = score_to_add
                                    event_type = "GQL_429"
                                    log_msg = f"[🛑 IP SCORING] {modem_name} ({real_ip}) GQL_429. Score: {curr_score} -> {new_score}"
                                else:
                                    new_score = max(0, curr_score - 2)  # 429 미발생 시 -2점 (최소 0점)
                                    change_amount = -2
                                    event_type = "CLEAN"
                                    log_msg = f"[🟢 IP SCORING] {modem_name} ({real_ip}) Completed clean. Score: {curr_score} -> {new_score}"
                            else:
                                new_score = curr_score
                                log_msg = f"[⚪ IP SCORING] {modem_name} ({real_ip}) neutral ({reason}). Score: {curr_score}"
                                
                            details["ip_score"] = new_score
                            details["last_score_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            if real_ip != "UNKNOWN":
                                details["current_ip"] = real_ip
                                
                            # Record to score history partition logs
                            try:
                                today_str = datetime.now().strftime("%Y%m%d")
                                history_dir = os.path.join(os.path.dirname(state_file), "rotator_history")
                                os.makedirs(history_dir, exist_ok=True)
                                history_file = os.path.join(history_dir, f"scoring_history_{today_str}.log")
                                if change_amount != 0:
                                    sign_str = f"+{change_amount}" if change_amount > 0 else str(change_amount)
                                    now_dt = datetime.now()
                                    time_stamp = now_dt.strftime("%H:%M:%S") + f".{now_dt.microsecond // 1000:03d}"
                                    start_time_str = "UNKNOWN"
                                    try:
                                        base_name = os.path.basename(log_dir)
                                        time_match = re.match(r'^(\d{2})(\d{2})(\d{2})_', base_name)
                                        if time_match:
                                            start_time_str = f"{time_match.group(1)}:{time_match.group(2)}:{time_match.group(3)}"
                                    except: pass
                                    end_time_str = now_dt.strftime("%H:%M:%S")
                                    time_range_str = f"({start_time_str} ~ {end_time_str})"
                                    record_line = f"[{time_stamp}] [{modem_name:<5}] ({real_ip:<15}) {event_type:<9} {time_range_str} -> Score: {curr_score:4d} -> {new_score:4d} (Change: {sign_str:<4})\n"
                                    with open(history_file, 'a', encoding='utf-8') as h_f:
                                        h_f.write(record_line)
                            except Exception as history_err:
                                print(f"[-] Error writing history record: {history_err}", file=sys.stderr)
                                
                            print(log_msg)
                            s_f.seek(0)
                            s_f.truncate()
                            json.dump(state_data, s_f, indent=2, ensure_ascii=False)
                    else:
                        print(f"[⚪ IP SCORING] Could not map real_ip {real_ip} or bind_ip {bind_ip} to any modem interface.")
        except Exception as score_err:
            print(f"[-] Error writing unified IP scores: {score_err}", file=sys.stderr)
            
        return leak_detected

if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("[!] Usage: python3 reporter.py <log_dir> <device_id> <task_id> <reason>", file=sys.stderr)
        sys.exit(2)
    leaked = IdentityAuditEngine.audit_and_score(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
    sys.exit(1 if leaked else 0)

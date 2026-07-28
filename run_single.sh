#!/usr/bin/env python3
# Nmap Multi V2: Pure Single Device Initial Value & Token Fetcher (V1 run_single.sh replacement)
import sys
import os
import time
import json
import subprocess

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src", "lib"))
from adb import ADBManager

def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  ./run_single.sh <DEVICE_INDEX (1..N) or SERIAL_ID>")
        print("Examples:")
        print("  ./run_single.sh 1")
        print("  ./run_single.sh R3CR70HT9BX")
        sys.exit(1)

    arg = sys.argv[1].strip()
    devices = ADBManager.get_connected_devices()
    if not devices:
        print("[-] Error: No active ADB devices connected.")
        sys.exit(1)

    dev_id = None
    if arg.isdigit():
        idx = int(arg) - 1
        if 0 <= idx < len(devices):
            dev_id = devices[idx]
        else:
            print(f"[-] Error: Index {arg} out of range (Found {len(devices)} active devices: 1..{len(devices)}).")
            sys.exit(1)
    else:
        if arg in devices:
            dev_id = arg
        else:
            print(f"[-] Error: Device '{arg}' not found in active devices: {', '.join(devices)}")
            sys.exit(1)

    dev_idx = devices.index(dev_id)
    mitm_port = 30000 + dev_idx + 1
    frida_port = 40000 + dev_idx + 1

    # Fetch alias from device ro.product.model
    model_res = ADBManager.run_adb(dev_id, "shell getprop ro.product.model")
    alias = model_res[0].strip().replace("SM-", "") or "UnknownDevice"

    print("============================================================")
    print(f"   ⚡ NMAP V2 PURE SINGLE FETCH: {alias} [{dev_id}] (Index #{dev_idx+1})")
    print(f"   MITM:{mitm_port} | FRIDA:{frida_port}")
    print("============================================================")

    # Log setup
    date_str = time.strftime("%Y%m%d")
    time_str = time.strftime("%H%M%S")
    capture_dir = os.path.join(PROJECT_ROOT, "logs", dev_id, date_str, f"{time_str}_original")
    os.makedirs(capture_dir, exist_ok=True)
    logs_dir = os.path.join(PROJECT_ROOT, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    pkg_name = "com.nhn.android.nmap"
    gps_pkg = "com.rosteam.gpsemulator"

    # 1. Cleanup old proxy & app state
    print(f"[*] Cleaning up previous processes for [{dev_id}]...")
    ADBManager.run_adb(dev_id, f"shell am force-stop {pkg_name}")
    ADBManager.run_adb(dev_id, f"shell am force-stop {gps_pkg}")
    ADBManager.run_adb(dev_id, "shell settings put global http_proxy :0")
    ADBManager.run_adb(dev_id, "reverse --remove-all")
    ADBManager.run_adb(dev_id, "forward --remove-all")
    subprocess.run(f"pkill -f 'mitmdump.*{mitm_port}'", shell=True)

    # 2. Smart Cache Purge
    print(f"[*] Performing data purge on [{dev_id}]...")
    ADBManager.run_adb(dev_id, f"shell \"su -c 'find /data/data/{pkg_name} -mindepth 1 -maxdepth 1 ! -name lib ! -name NaverNavi -exec rm -rf {{}} +'\"")

    # 3. Setup Proxy Tunnel
    print(f"[*] Establishing reverse proxy tunnel (localhost:{mitm_port})...")
    ADBManager.run_adb(dev_id, f"reverse tcp:{mitm_port} tcp:{mitm_port}")
    ADBManager.run_adb(dev_id, f"shell settings put global http_proxy localhost:{mitm_port}")

    # 4. Launch mitmdump with V2 addon
    mitm_addon_script = os.path.join(PROJECT_ROOT, "src", "mitm", "addon.py")
    mitm_log_path = os.path.join(capture_dir, "mitm.log")
    env = os.environ.copy()
    env["CAPTURE_LOG_DIR"] = capture_dir
    env["PYTHONWARNINGS"] = "ignore"

    mitm_proc = subprocess.Popen(
        ["mitmdump", "-p", str(mitm_port), "-s", mitm_addon_script, "--ssl-insecure", "--listen-host", "0.0.0.0", "--set", "flow_detail=0"],
        stdout=open(mitm_log_path, "w"), stderr=subprocess.STDOUT, env=env
    )

    # 5. Frida Port Forward & App Launch
    ADBManager.run_adb(dev_id, f"forward tcp:{frida_port} tcp:27042")
    print(f"[*] Launching Naver Map on [{dev_id}]...")
    ADBManager.run_adb(dev_id, f"shell monkey -p {pkg_name} -c android.intent.category.LAUNCHER 1")

    # Poll for PID
    pid = None
    for _ in range(10):
        pid_res = ADBManager.run_adb(dev_id, f"shell pidof {pkg_name}")
        if pid_res[0].strip() and pid_res[0].strip().split()[0].isdigit():
            pid = pid_res[0].strip().split()[0]
            break
        time.sleep(1)

    frida_proc = None
    if pid:
        print(f"[✓] App launched (PID: {pid}). Attaching Frida instrumentation hooks...")
        frida_log_path = os.path.join(capture_dir, "frida.log")
        frida_script = os.path.join(PROJECT_ROOT, "src", "frida", "network_hook.js")
        frida_proc = subprocess.Popen(
            ["frida", "-H", f"127.0.0.1:{frida_port}", "--runtime=v8", "-p", pid, "-l", frida_script, "--no-auto-reload"],
            stdout=open(frida_log_path, "w"), stderr=subprocess.STDOUT
        )

    print("\n============================================================")
    print(f" ⌛ Monitoring [{dev_id}] for complete nlogapp packet capture...")
    print("============================================================\n")

    def cleanup():
        print(f"\n[*] Finalizing session & restoring device state for [{dev_id}]...")
        if mitm_proc:
            try: mitm_proc.terminate()
            except: pass
        if frida_proc:
            try: frida_proc.terminate()
            except: pass
        ADBManager.run_adb(dev_id, f"shell am force-stop {pkg_name}")
        ADBManager.run_adb(dev_id, "shell settings put global http_proxy :0")
        ADBManager.run_adb(dev_id, "reverse --remove-all")
        ADBManager.run_adb(dev_id, "forward --remove-all")

    start_time = time.time()
    extracted = False
    try:
        while time.time() - start_time < 90:
            for root, _, files in os.walk(capture_dir):
                for fname in files:
                    if fname.endswith("nlogapp.json") and not fname.endswith(".incomplete"):
                        fpath = os.path.join(root, fname)
                        try:
                            with open(fpath, "r", encoding="utf-8") as jf:
                                data = json.load(jf)

                            body = data.get("request", {}).get("body", {})
                            usr = body.get("usr", {})
                            evts = body.get("evts", [])

                            adid = usr.get("adid")
                            ssaid = usr.get("ssaid")
                            idfv = usr.get("idfv")
                            ni = usr.get("ni")
                            token = None
                            if evts and isinstance(evts, list) and len(evts) > 0 and "nlog_id" in evts[0]:
                                full_nlog_id = str(evts[0].get("nlog_id", ""))
                                token = full_nlog_id.split(".")[-1] if "." in full_nlog_id else full_nlog_id

                            if adid and ssaid and idfv and ni and adid != "null" and ssaid != "null":
                                sql_insert = f"INSERT INTO `devices`(`device_id`, `alias`, `orig_ssaid`, `orig_adid`, `orig_idfv`, `orig_ni`, `orig_token`) VALUES ('{dev_id}', '{alias}', '{ssaid}', '{adid}', '{idfv}', '{ni}', '{token or ''}');"
                                sql_update = f"UPDATE `devices` SET `alias`='{alias}', `orig_ssaid`='{ssaid}', `orig_adid`='{adid}', `orig_idfv`='{idfv}', `orig_ni`='{ni}', `orig_token`='{token or ''}' WHERE `device_id`='{dev_id}';"

                                print("============================================================")
                                print(f" [✓] [{alias}] Complete Data Set Captured: {fname}")
                                print("============================================================")
                                print("\n--- GENERATED SQL QUERY ---")
                                print(sql_insert)
                                print("----------------------------\n")

                                insert_path = os.path.join(logs_dir, "insert.txt")
                                update_path = os.path.join(logs_dir, "update.txt")

                                with open(insert_path, "a", encoding="utf-8") as f_ins:
                                    f_ins.write(sql_insert + "\n")
                                print(f"[!] Query appended to: {insert_path}")

                                with open(update_path, "a", encoding="utf-8") as f_up:
                                    f_up.write(sql_update + "\n")
                                print(f"[!] Query appended to: {update_path}")

                                extracted = True
                                break
                        except Exception:
                            pass
                if extracted:
                    break
            if extracted:
                break
            time.sleep(2)

        if not extracted:
            print("[-] Timeout (90s) waiting for complete nlogapp identity capture.")

    finally:
        cleanup()

if __name__ == "__main__":
    main()

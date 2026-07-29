import subprocess
import xml.etree.ElementTree as ET
from xml.dom import minidom
import random
import time
import os
import sys
import json
import glob
import re

def save_multiline_xml(tree_root, file_path):
    """Saves XML tree as a pretty-printed, multiline file"""
    rough_string = ET.tostring(tree_root, 'utf-8')
    reparsed = minidom.parseString(rough_string)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(reparsed.toprettyxml(indent="  "))

def get_ui_dump_pair(device_id, category_name):
    """Captures Multiline XML and optionally Screenshot strictly into the session log folder"""
    log_dir = os.environ.get("CAPTURE_LOG_DIR")
    if not log_dir or not os.path.exists(log_dir):
        print(f" [!] FATAL ERROR: Session log directory missing")
        return None, None

    target_dir = os.path.join(log_dir, "screenshot", category_name)
    os.makedirs(target_dir, exist_ok=True)
    
    timestamp = time.strftime("%H%M%S")
    xml_file = os.path.join(target_dir, f"capture_{device_id}_{timestamp}.xml")
    
    try:
        # 기기별 격리된 tmp 폴더 경로 확보
        dev_tmp_dir = f"/home/tech/nmap_multi_v2/logs/devices/{device_id}/tmp"
        os.makedirs(dev_tmp_dir, exist_ok=True)
        
        subprocess.run(["adb", "-s", device_id, "shell", "uiautomator", "dump", "/sdcard/ui.xml"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=15)
        temp_xml = os.path.join(dev_tmp_dir, f"raw_{device_id}.xml")
        subprocess.run(["adb", "-s", device_id, "pull", "/sdcard/ui.xml", temp_xml], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=10)
        tree = ET.parse(temp_xml)
        save_multiline_xml(tree.getroot(), xml_file)
        os.remove(temp_xml)

        png_file = None
        if os.environ.get("CAPTURE_SCREENSHOT") == "true":
            png_file = os.path.join(target_dir, f"capture_{device_id}_{timestamp}.png")
            subprocess.run(["adb", "-s", device_id, "shell", "screencap", "-p", "/sdcard/screen.png"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=10)
            subprocess.run(["adb", "-s", device_id, "pull", "/sdcard/screen.png", png_file], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=10)

        return xml_file, png_file
    except subprocess.TimeoutExpired:
        print(f" [-] Capture Pair Timeout (15s)")
        return None, None
    except Exception as e:
        print(f" [-] Capture Pair Fail: {e}")
        return None, None

def check_fatal_errors(xml_file):
    """Check for UI states that indicate definitive failure (No results, unreachable)"""
    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()
        fatal_messages = [
            "검색 결과가 없습니다",
            "결과를 제공할 수 없습니다",
            "검색 결과가 없어요",
            "장소를 찾을 수 없습니다",
            "길찾기 결과를 제공할 수 없습니다",
            "길찾기 결과가 없습니다"
        ]
        for node in root.iter():
            text = (node.get('text') or "").strip()
            for msg in fatal_messages:
                if msg in text:
                    return True, text
        return False, None
    except:
        return False, None

def check_and_dismiss_popups(device_id, xml_file, category):
    """Check for known blocking popups like cache clearing and dismiss them"""
    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()
        is_popup_present = False
        
        for node in root.iter():
            text = (node.get('text') or "").strip()
            if ("캐시" in text and "삭제" in text) or ("서비스 오류" in text) or ("다시 시도" in text):
                is_popup_present = True
                break
                
        if is_popup_present:
            print(f" [!] Interstitial Popup Detected. Dismissing...")
            for node in root.iter():
                text = (node.get('text') or "").strip()
                if text in ["확인", "예", "삭제", "다시 시도"]:
                    bounds_str = node.get('bounds')
                    if bounds_str:
                        coords = [int(c) for c in bounds_str.replace('][', ',').replace('[', '').replace(']', '').split(',')]
                        tx = (coords[0] + coords[2]) // 2
                        ty = (coords[1] + coords[3]) // 2
                        subprocess.run(["adb", "-s", device_id, "shell", "input", "tap", str(tx), str(ty)])
                        print(f" [✓] Dismissed popup by clicking '{text}'")
                        time.sleep(2)
                        return get_ui_dump_pair(device_id, category)
                        
    except: pass
    return xml_file, None

def find_element(xml_file, query):
    """Pure dynamic discovery with Flexible Address Matching"""
    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()
        mode, val = query.split(':', 1)
        
        matches = []
        for node in root.iter():
            match = False
            node_text = (node.get('text') or "").strip()
            node_id = (node.get('resource-id') or "")
            node_desc = (node.get('content-desc') or "")
            
            if mode == "text": 
                clean_val = val
                if "," in clean_val and len(clean_val.split()) > 2:
                    clean_val = clean_val.split(',')[0].strip()
                
                words = clean_val.split()
                if len(words) > 2:
                    match_target = " ".join(words[2:])
                else:
                    match_target = clean_val
                match = match_target in node_text
            elif mode == "contains": match = (val in node_text) or (val in node_desc)
            elif mode == "exact": match = node_text == val
            elif mode == "id": match = node_id == val
            elif mode == "desc": match = val in node_desc
            
            if match:
                bounds_str = node.get('bounds')
                if not bounds_str: continue
                coords = [int(c) for c in bounds_str.replace('][', ',').replace('[', '').replace(']', '').split(',')]
                
                score = 0
                x1, y1, x2, y2 = coords
                width, height = x2 - x1, y2 - y1
                area = width * height
                clickable = node.get('clickable', 'false').lower() == 'true'

                if node_text == val: score += 100 
                if clickable: score += 50
                if area > (1080 * 2000 * 0.8): score -= 200
                if area <= 0: score -= 500
                if y1 > 1500: score += 30
                if len(node_text) > len(val) + 10: score -= 30
                if node.get('class') == 'android.view.View' and not clickable: score -= 50
                if 10 < width < 1000 and 10 < height < 500: score += 20
                
                matches.append({
                    'node': node, 'coords': coords, 'checked': node.get('checked', 'false').lower() == 'true',
                    'score': score, 'area': area, 'text': node_text
                })
        
        if not matches: return None, False, None
        
        matches.sort(key=lambda x: (-x['score'], x['area']))
        best = matches[0]
        
        return best['coords'], best['checked'], best['text']
    except Exception as e:
        print(f" [-] find_element Error: {e}")
        return None, False, None

def check_search_failure(log_dir):
    """Analyzes instantSearchV2.json packets in log_dir to determine the failure cause"""
    if not log_dir or not os.path.exists(log_dir):
        return "ADDRESS_NOT_FOUND"
        
    search_files = glob.glob(os.path.join(log_dir, "**/*instantSearchV2.json"), recursive=True)
    if not search_files:
        return "TYPING_FAILED"
        
    network_error = True
    for file_path in search_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            response = data.get("response", {})
            status_code = response.get("status_code", 0)
            if status_code != 200:
                continue
            body = response.get("body", {})
            ac = body.get("ac", [])
            place = body.get("place", [])
            if len(ac) > 0 or len(place) > 0:
                network_error = False
                break
        except Exception:
            continue
            
    if network_error:
        return "NETWORK_ERROR_OR_TIMEOUT"
    return "ADDRESS_NOT_FOUND"

def report_fail(log_id, device_id, status, requested, actual, error):
    """Report failure details to API Server with current log path"""
    if not log_id: return
    log_path = os.environ.get("CAPTURE_LOG_DIR", "Unknown")
    
    if log_path != "Unknown":
        reason = check_search_failure(log_path)
        if reason != "ADDRESS_NOT_FOUND":
            status = f"FAIL_{reason}"
            error = f"{error} (Determined cause: {reason})"
            
    data = {
        "task_id": int(log_id), "device_id": device_id, "status": status, 
        "requested_address": requested, "actual_address": actual, 
        "error_msg": error, "log_path": log_path
    }
    api_server = os.environ.get('API_SERVER', '114.207.112.245:8013')
    try:
        subprocess.run(["curl", "-s", "--connect-timeout", "5", "-X", "POST", f"http://{api_server}/api/v1/update_status", "-H", "Content-Type: application/json", "-d", json.dumps(data)], stdout=subprocess.DEVNULL, timeout=10)
    except: pass

def click_element(device_id, query, padding=10, category="default"):
    """Executes dynamic click with failure reporting and robust heuristics"""
    log_id = os.environ.get("NMAP_LOG_ID")
    last_actual_text = "Not Found"
    
    for attempt in range(3):
        xml_path, png_path = get_ui_dump_pair(device_id, category)
        if not xml_path: time.sleep(2); continue

        xml_path, _ = check_and_dismiss_popups(device_id, xml_path, category)
        if not xml_path: time.sleep(2); continue

        fatal, text = check_fatal_errors(xml_path)
        if fatal:
            error_msg = f"POI search returned fatal UI state: '{text}'"
            print(f" [!] FATAL SEARCH ERROR: {error_msg}")
            req_addr = os.environ.get("NMAP_DEST_ADDR", "Unknown")
            report_fail(log_id, device_id, "FAIL_ADDRESS_NOT_FOUND", req_addr, text, error_msg)
            return False

        coords, checked, actual_text = find_element(xml_path, query)
        if coords:
            x1, y1, x2, y2 = coords
            # Click center with slight random offset
            cx = (x1 + x2) // 2 + random.randint(-padding, padding)
            cy = (y1 + y2) // 2 + random.randint(-padding, padding)
            print(f"  [✓] [{query}] element found at bounds: {coords} -> Tapping ({cx}, {cy}) (Checked: {checked})")
            subprocess.run(["adb", "-s", device_id, "shell", "input", "tap", str(cx), str(cy)])
            return True
            
        time.sleep(1.5)
        
    print(f"  [-] Element '{query}' not found in 3 attempts.")
    return False

def chain_click(device_id, queries, padding=10, category="default"):
    for q in queries:
        if not click_element(device_id, q, padding, category):
            return False
        time.sleep(1)
    return True

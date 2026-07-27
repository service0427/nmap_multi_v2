#!/usr/bin/env python3
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ui_clicker

MACRO_MAP = {
    "entry_search_field": {
        "queries": ["exact:네이버지도 검색"],
        "padding": 0,
        "desc": "메인 화면 검색창 진입"
    },
    "btn_start_guidance": {
        "queries": ["exact:안내시작"],
        "padding": 15,
        "desc": "자동차 길찾기 시작"
    },
    "btn_start_guidance_modal": {
        "queries": ["exact:안내시작"],
        "padding": 10,
        "desc": "영업시간 알림 모달 내 안내시작"
    },
    "btn_end_guidance": {
        "queries": ["text:안내종료"],
        "padding": 15,
        "desc": "목적지 도착 후 안내 종료"
    }
}

class MacroExecutor:
    @classmethod
    def run_step(cls, device_id, step_id, category="default"):
        query_prefixes = ["text:", "exact:", "id:", "desc:", "contains:"]
        if any(step_id.startswith(prefix) for prefix in query_prefixes):
            print(f"[*] Executing Direct Query: {step_id}")
            return ui_clicker.click_element(device_id, step_id, category=category)

        if step_id in MACRO_MAP:
            cfg = MACRO_MAP[step_id]
            print(f"[*] Macro [{step_id}] Started: {cfg['desc']}")
            queries = cfg["queries"]
            padding = cfg.get("padding", 10)
            
            if len(queries) == 1:
                return ui_clicker.click_element(device_id, queries[0], padding=padding, category=category)
            else:
                return ui_clicker.chain_click(device_id, queries, padding=padding, category=category)

        print(f" [-] Error: Unknown Macro ID or Query Format: '{step_id}'")
        return False

if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(1)
    dev_id = sys.argv[1]
    raw_step_arg = sys.argv[2]
    query_prefixes = ["text:", "exact:", "id:", "desc:", "contains:"]
    if any(raw_step_arg.startswith(prefix) for prefix in query_prefixes):
        steps = [raw_step_arg]
    else:
        steps = raw_step_arg.split(',')
    cat = sys.argv[3] if len(sys.argv) >= 4 else "default"
    
    success = True
    for s in steps:
        if not MacroExecutor.run_step(dev_id, s.strip(), category=cat):
            success = False
            break
            
    sys.exit(0 if success else 1)

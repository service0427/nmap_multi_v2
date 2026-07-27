import os
import json
import datetime

# 1. 네이버 지도 정식 서비스 도메인 화이트리스트
ALLOWED_DOMAINS = [
    "naver.com",
    "navercorp.com",
    "pstatic.net",
    "clova.ai",
    "ncloud.com",
    "naver.net",
    "navercdn.com"
]

# 2. 로깅/수집에서 배제할 정적 미디어 및 노이즈 확장자
NOISE_EXTS = [
    ".mvt", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico",
    ".woff", ".woff2", ".ttf", ".otf", ".eot", ".svg",
    ".js", ".css", ".sdf", ".map"
]

# 3. 비필수 트래커 및 노이즈 호스트/경로 패턴
NOISE_PATTERNS = [
    "tivan.naver.com",
    "map.pstatic.net",
    "analytics",
    "appmetrica",
    "yandex",
    "firebase",
    "crashlytics",
    "facebook",
    "ad.mail.ru",
    "client-logger/errorlog"
]

def log_filtered_url(host: str, path: str, reason: str):
    """Logs the filtered URL into the session log directory for future reference"""
    log_dir = os.environ.get("CAPTURE_LOG_DIR")
    if not log_dir or not os.path.exists(log_dir):
        return

    log_file = os.path.join(log_dir, "filtered_urls.jsonl")
    data = {
        "timestamp": datetime.datetime.now().isoformat(),
        "reason": reason,
        "host": host,
        "path": path
    }

    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
    except:
        pass

def should_process(host: str, path: str) -> bool:
    host_lower = host.lower()
    path_lower = path.lower()
    full_url = f"{host_lower}{path_lower}"

    # Rule A: 허용 도메인 화이트리스트 검사
    is_allowed = any(dom in host_lower for dom in ALLOWED_DOMAINS)
    if not is_allowed:
        log_filtered_url(host, path, "NON_WHITELIST_DOMAIN")
        return False

    # Rule B: 정적 미디어/노이즈 확장자 차단
    for ext in NOISE_EXTS:
        if ext in path_lower:
            log_filtered_url(host, path, f"EXTENSION_{ext.strip('.').upper()}")
            return False

    # Rule C: 서드파티 트래커 및 노이즈 호스트/경로 차단
    for pat in NOISE_PATTERNS:
        if pat in full_url:
            log_filtered_url(host, path, f"NOISE_PATTERN_{pat.upper().replace('.', '_').replace('/', '_')}")
            return False

    return True

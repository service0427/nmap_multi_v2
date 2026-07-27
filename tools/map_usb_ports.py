#!/usr/bin/env python3
import os
import sys

V2_ROOT = "/home/tech/nmap_multi_v2"
sys.path.insert(0, os.path.join(V2_ROOT, "src", "lib"))

try:
    import manifest
    print("[*] Rebuilding devices_manifest.json...")
    data = manifest.auto_generate_manifest()
    print(f"[✓] Successfully rebuilt devices_manifest.json with {len(data)} devices!")
    sys.exit(0)
except Exception as e:
    print(f"[-] Rebuild failed: {e}")
    sys.exit(1)

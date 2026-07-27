#!/usr/bin/env python3
import os
import fcntl

V2_ROOT = "/home/tech/nmap_multi_v2"

class DeviceLock:
    """Manages execution lock for a single device to prevent concurrent scheduler launches."""
    def __init__(self, device_id):
        self.device_id = device_id
        self.lock_path = os.path.join(V2_ROOT, "logs", "devices", device_id, "tmp", "nmap_lock")
        self.lock_file = None

    def acquire(self):
        """Attempts to acquire non-blocking lock. Returns True if successful."""
        try:
            os.makedirs(os.path.dirname(self.lock_path), exist_ok=True)
            self.lock_file = open(self.lock_path, "a+")
            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (IOError, BlockingIOError):
            self.close()
            return False

    def release(self):
        """Releases the lock and removes lock file."""
        if self.lock_file:
            try:
                fcntl.flock(self.lock_file, fcntl.LOCK_UN)
            except: pass
            self.close()
            try:
                if os.path.exists(self.lock_path):
                    os.remove(self.lock_path)
            except: pass

    def close(self):
        if self.lock_file:
            try:
                self.lock_file.close()
            except: pass
            self.lock_file = None


class SubnetLock:
    """Manages launch serialization (staggering) lock for devices on the same LTE subnet."""
    def __init__(self, subnet_idx):
        self.subnet_idx = str(subnet_idx)
        self.lock_path = os.path.join(V2_ROOT, "logs", "locks", f"subnet_{self.subnet_idx}_launch.lock")
        self.lock_file = None

    def acquire(self):
        """Attempts to acquire non-blocking launch lock. Returns True if successful."""
        try:
            os.makedirs(os.path.dirname(self.lock_path), exist_ok=True)
            self.lock_file = open(self.lock_path, "a+")
            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (IOError, BlockingIOError):
            self.close()
            return False

    def release(self):
        """Releases the subnet lock."""
        if self.lock_file:
            try:
                fcntl.flock(self.lock_file, fcntl.LOCK_UN)
            except: pass
            self.close()

    def close(self):
        if self.lock_file:
            try:
                self.lock_file.close()
            except: pass
            self.lock_file = None

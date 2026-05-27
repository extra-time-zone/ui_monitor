import json
import os
import time
from typing import Optional


class PersistentAlertDeduper:
    def __init__(self, path: str, ttl_seconds: int):
        self.path = path
        self.ttl_seconds = ttl_seconds
        self.items = self._load()

    def should_alert(self, key: str, now: Optional[float] = None) -> bool:
        current = now or time.time()
        self.cleanup(current)

        last_seen = self.items.get(key)
        if last_seen and current - last_seen < self.ttl_seconds:
            return False

        self.items[key] = current
        self._save()
        return True

    def cleanup(self, now: Optional[float] = None):
        current = now or time.time()
        expired = [
            key
            for key, ts in self.items.items()
            if current - float(ts or 0) > self.ttl_seconds
        ]
        if not expired:
            return
        for key in expired:
            self.items.pop(key, None)
        self._save()

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                return {
                    str(key): float(value)
                    for key, value in data.items()
                    if isinstance(value, (int, float))
                }
        except FileNotFoundError:
            pass
        except Exception as exc:
            print(f"[DEDUPE] load failed: {exc}", flush=True)
        return {}

    def _save(self):
        try:
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            temp_path = f"{self.path}.tmp"
            with open(temp_path, "w", encoding="utf-8") as handle:
                json.dump(self.items, handle, sort_keys=True)
            os.replace(temp_path, self.path)
        except Exception as exc:
            print(f"[DEDUPE] save failed: {exc}", flush=True)

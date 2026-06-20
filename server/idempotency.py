"""Tiny persistent idempotency store. Maps an Idempotency-Key to the response
(status code + JSON body) that was returned, so a retried mutating request replays the
same result rather than applying the change twice. Persisted to a JSON file in the
vault (gitignored), atomically (tmp + os.replace), so it survives restarts."""
import json
import os


class IdempotencyStore:
    def __init__(self, path):
        self.path = path
        self._data = {}
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    self._data = loaded
            except (ValueError, OSError):
                self._data = {}   # corrupt/unreadable -> start empty, never crash

    def get(self, key):
        return self._data.get(key)

    def put(self, key, status_code, body):
        self._data[key] = {"status_code": status_code, "body": body}
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False)
        os.replace(tmp, self.path)

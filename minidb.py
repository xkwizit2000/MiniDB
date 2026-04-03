# minidb.py
#
# Based on https://github.com/rogue-agent1/minidb by rogue-agent1
# Modifications: atomic writes, TTL support, file locking, batch ops,
#                stored None fix, get() default parameter
#
# MIT License
#
# Copyright (c) 2026 John (JT) Thornton
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

import json, os, time, tempfile
from contextlib import contextmanager

__version__ = "0.2.0"

_MISSING = object()  # sentinel to distinguish missing keys from stored None

try:
    import fcntl
    LOCK_AVAILABLE = "fcntl"
except ImportError:
    try:
        import msvcrt
        LOCK_AVAILABLE = "msvcrt"
    except ImportError:
        LOCK_AVAILABLE = None


class LockError(Exception):
    pass


class MiniDB:
    def __init__(self, path="minidb.json", lock_timeout=5):
        self.path = path
        self.lock_path = path + ".lock"
        self.lock_timeout = lock_timeout
        self.data = {}
        self._load()

    @contextmanager
    def _lock(self):
        lock_file = open(self.lock_path, "w")
        acquired = False
        deadline = time.time() + self.lock_timeout

        try:
            if LOCK_AVAILABLE == "fcntl":
                while True:
                    try:
                        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        acquired = True
                        break
                    except BlockingIOError:
                        if time.time() > deadline:
                            raise LockError(f"Could not acquire lock on {self.lock_path} within {self.lock_timeout}s")
                        time.sleep(0.05)

            elif LOCK_AVAILABLE == "msvcrt":
                while True:
                    try:
                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                        acquired = True
                        break
                    except OSError:
                        if time.time() > deadline:
                            raise LockError(f"Could not acquire lock on {self.lock_path} within {self.lock_timeout}s")
                        time.sleep(0.05)

            else:
                while True:
                    try:
                        fd = os.open(self.lock_path + ".sentinel", os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                        os.close(fd)
                        acquired = True
                        break
                    except FileExistsError:
                        if time.time() > deadline:
                            raise LockError(f"Could not acquire lock on {self.lock_path} within {self.lock_timeout}s")
                        time.sleep(0.05)

            yield

        finally:
            if LOCK_AVAILABLE == "fcntl" and acquired:
                fcntl.flock(lock_file, fcntl.LOCK_UN)
            elif LOCK_AVAILABLE == "msvcrt" and acquired:
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            elif acquired:
                sentinel = self.lock_path + ".sentinel"
                if os.path.exists(sentinel):
                    os.remove(sentinel)
            lock_file.close()

    def _load(self):
        if os.path.exists(self.path):
            with open(self.path) as f:
                self.data = json.load(f)

    def _save(self):
        dir_name = os.path.dirname(self.path) or "."
        with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, suffix=".tmp") as tmp:
            json.dump(self.data, tmp)
            tmp_path = tmp.name
        os.replace(tmp_path, self.path)

    def _reload(self):
        if os.path.exists(self.path):
            with open(self.path) as f:
                self.data = json.load(f)

    def put(self, key, value, ttl=None):
        expires_at = time.time() + ttl if ttl is not None else None
        with self._lock():
            self._reload()
            self.data[key] = {"v": value, "ts": time.time(), "exp": expires_at}
            self._save()

    def put_many(self, items, ttl=None):
        if isinstance(items, dict):
            items = list(items.items())
        now = time.time()
        with self._lock():
            self._reload()
            for item in items:
                if len(item) == 3:
                    key, value, item_ttl = item
                else:
                    key, value = item
                    item_ttl = ttl
                expires_at = now + item_ttl if item_ttl is not None else None
                self.data[key] = {"v": value, "ts": now, "exp": expires_at}
            self._save()

    def get(self, key, default=_MISSING):
        with self._lock():
            self._reload()
            e = self.data.get(key, _MISSING)
            if e is _MISSING:
                return None if default is _MISSING else default
            if e.get("exp") is not None and time.time() > e["exp"]:
                self.data.pop(key)
                self._save()
                return None if default is _MISSING else default
            return e["v"]

    def get_many(self, keys):
        now = time.time()
        with self._lock():
            self._reload()
            result = {}
            expired = []
            for key in keys:
                e = self.data.get(key)
                if e is None:
                    continue
                if e.get("exp") is not None and now > e["exp"]:
                    expired.append(key)
                    continue
                result[key] = e["v"]
            if expired:
                for k in expired:
                    self.data.pop(k, None)
                self._save()
        return result

    def delete(self, key):
        with self._lock():
            self._reload()
            self.data.pop(key, None)
            self._save()

    def delete_many(self, keys):
        with self._lock():
            self._reload()
            for key in keys:
                self.data.pop(key, None)
            self._save()

    def exists(self, key):
        with self._lock():
            self._reload()
            e = self.data.get(key)
            if e is None:
                return False
            if e.get("exp") is not None and time.time() > e["exp"]:
                self.data.pop(key)
                self._save()
                return False
            return True

    def keys(self):
        with self._lock():
            self._reload()
            now = time.time()
            return [k for k, v in self.data.items()
                    if v.get("exp") is None or now <= v["exp"]]

    def scan(self, prefix=""):
        with self._lock():
            self._reload()
            now = time.time()
            return {k: v["v"] for k, v in self.data.items()
                    if k.startswith(prefix)
                    and (v.get("exp") is None or now <= v["exp"])}

    def count(self):
        return len(self.keys())

    def compact(self):
        with self._lock():
            self._reload()
            now = time.time()
            expired = [k for k, v in self.data.items()
                       if v.get("exp") is not None and now > v["exp"]]
            for k in expired:
                self.data.pop(k)
            self._save()
        return len(self.data)

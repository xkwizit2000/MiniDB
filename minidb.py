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

import json, os, time, tempfile, threading, atexit
from contextlib import contextmanager

__version__ = "0.5.0"

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
    def __init__(self, path="minidb.json", lock_timeout=5,
                 flush_interval=None, flush_ops=None):
        self.path = path
        self.lock_path = path + ".lock"
        self.lock_timeout = lock_timeout
        self.data = {}
        self._in_transaction = False  # True while inside a transaction block
        self._tx_snapshot = None      # pre-transaction snapshot for rollback

        # Write buffering
        self._flush_interval = flush_interval  # seconds between auto-flushes
        self._flush_ops = flush_ops            # op count threshold for auto-flush
        self._buffering = flush_interval is not None or flush_ops is not None
        self._dirty = False                    # True if unflushed mutations exist
        self._op_count = 0                     # mutations since last flush
        self._timer = None                     # active threading.Timer
        self._buffer_lock = threading.Lock()   # protects dirty/op_count/timer state

        self._load()

        if self._buffering:
            atexit.register(self.close)
            if self._flush_interval is not None:
                self._schedule_timer()

    def _schedule_timer(self):
        """Schedule the next interval flush. Cancels any existing timer first."""
        if self._timer is not None:
            self._timer.cancel()
        self._timer = threading.Timer(self._flush_interval, self._timer_flush)
        self._timer.daemon = True
        self._timer.start()

    def _timer_flush(self):
        """Called by the timer thread - flush if dirty, then reschedule."""
        self.flush()
        if self._flush_interval is not None:
            self._schedule_timer()

    def _mark_dirty(self):
        """
        Record a mutation. If buffering is off, does nothing (_save handles it).
        If buffering is on, increments op count and triggers flush if threshold hit.
        """
        if not self._buffering:
            return
        with self._buffer_lock:
            self._dirty = True
            self._op_count += 1
            if self._flush_ops is not None and self._op_count >= self._flush_ops:
                self._do_flush()

    def _do_flush(self):
        """
        Internal unconditional flush. Caller must hold _buffer_lock.
        Resets dirty flag and op counter.
        """
        if not self._dirty:
            return
        self._flush()
        self._dirty = False
        self._op_count = 0

    def flush(self):
        """
        Manually flush all buffered writes to disk immediately.
        Safe to call at any time. No-op if nothing is buffered or dirty.
        """
        with self._buffer_lock:
            self._do_flush()

    def close(self):
        """
        Flush any remaining buffered writes and stop the background timer.
        Called automatically on process exit via atexit when buffering is enabled.
        """
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self.flush()

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
        # Inside a transaction, suppress writes - commit() flushes once at the end
        if self._in_transaction:
            return
        # In buffering mode, mark dirty instead of writing immediately
        if self._buffering:
            self._mark_dirty()
            return
        dir_name = os.path.dirname(self.path) or "."
        with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, suffix=".tmp") as tmp:
            json.dump(self.data, tmp)
            tmp_path = tmp.name
        os.replace(tmp_path, self.path)

    def _flush(self):
        """Unconditional write to disk - used by transactions and buffer flushes."""
        dir_name = os.path.dirname(self.path) or "."
        with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, suffix=".tmp") as tmp:
            json.dump(self.data, tmp)
            tmp_path = tmp.name
        os.replace(tmp_path, self.path)

    def _reload(self):
        # Inside a transaction, don't reload from disk - work against the snapshot
        if self._in_transaction:
            return
        if os.path.exists(self.path):
            with open(self.path) as f:
                self.data = json.load(f)

    @contextmanager
    def transaction(self):
        """
        Atomic transaction block. All writes are held in memory and flushed
        in a single _save() on success. Any exception triggers a full rollback
        to the pre-transaction state - nothing is written to disk.

        Usage:
            with db.transaction():
                db.put("a", 1)
                db.put("b", 2)
                db.delete("c")
            # All three ops committed atomically, or none if an exception occurred.

        Transactions acquire the file lock for their entire duration.
        Nested transactions are not supported and will raise RuntimeError.
        """
        if self._in_transaction:
            raise RuntimeError("Nested transactions are not supported")

        with self._lock():
            self._reload()
            self._tx_snapshot = {k: dict(v) for k, v in self.data.items()}
            self._in_transaction = True
            try:
                yield
                # Success - flush all buffered changes in one write
                self._flush()
            except Exception:
                # Rollback - restore pre-transaction state, nothing written to disk
                self.data = self._tx_snapshot
                raise
            finally:
                self._in_transaction = False
                self._tx_snapshot = None

    def put(self, key, value, ttl=None):
        expires_at = time.time() + ttl if ttl is not None else None
        if self._in_transaction:
            self.data[key] = {"v": value, "ts": time.time(), "exp": expires_at}
            return
        with self._lock():
            self._reload()
            self.data[key] = {"v": value, "ts": time.time(), "exp": expires_at}
            self._save()

    def put_many(self, items, ttl=None):
        if isinstance(items, dict):
            items = list(items.items())
        now = time.time()
        if self._in_transaction:
            for item in items:
                if len(item) == 3:
                    key, value, item_ttl = item
                else:
                    key, value = item
                    item_ttl = ttl
                expires_at = now + item_ttl if item_ttl is not None else None
                self.data[key] = {"v": value, "ts": now, "exp": expires_at}
            return
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
        if self._in_transaction:
            e = self.data.get(key, _MISSING)
            if e is _MISSING:
                return None if default is _MISSING else default
            if e.get("exp") is not None and time.time() > e["exp"]:
                self.data.pop(key)
                return None if default is _MISSING else default
            return e["v"]
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
        if self._in_transaction:
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
            for k in expired:
                self.data.pop(k, None)
            return result
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
        if self._in_transaction:
            self.data.pop(key, None)
            return
        with self._lock():
            self._reload()
            self.data.pop(key, None)
            self._save()

    def delete_many(self, keys):
        if self._in_transaction:
            for key in keys:
                self.data.pop(key, None)
            return
        with self._lock():
            self._reload()
            for key in keys:
                self.data.pop(key, None)
            self._save()

    def exists(self, key):
        if self._in_transaction:
            e = self.data.get(key)
            if e is None:
                return False
            if e.get("exp") is not None and time.time() > e["exp"]:
                self.data.pop(key)
                return False
            return True
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
        if self._in_transaction:
            now = time.time()
            return [k for k, v in self.data.items()
                    if v.get("exp") is None or now <= v["exp"]]
        with self._lock():
            self._reload()
            now = time.time()
            return [k for k, v in self.data.items()
                    if v.get("exp") is None or now <= v["exp"]]

    def scan(self, prefix=""):
        if self._in_transaction:
            now = time.time()
            return {k: v["v"] for k, v in self.data.items()
                    if k.startswith(prefix)
                    and (v.get("exp") is None or now <= v["exp"])}
        with self._lock():
            self._reload()
            now = time.time()
            return {k: v["v"] for k, v in self.data.items()
                    if k.startswith(prefix)
                    and (v.get("exp") is None or now <= v["exp"])}

    def _query_rows(self, prefix, where, columns, order_by, limit, skip_invalid, now):
        """
        Core query logic shared between transaction and non-transaction paths.
        Returns a list of result dicts, each with a '_key' field added.
        """
        rows = []
        for k, entry in self.data.items():
            if not k.startswith(prefix):
                continue
            if entry.get("exp") is not None and now > entry["exp"]:
                continue
            v = entry["v"]
            if not isinstance(v, dict):
                if skip_invalid:
                    continue
                raise TypeError(
                    f"query() requires dict values - key '{k}' has type "
                    f"{type(v).__name__}. Use skip_invalid=True to skip non-dict values."
                )
            if where is not None and not where(v):
                continue
            row = {"_key": k, **v}
            rows.append(row)

        if order_by is not None:
            reverse = order_by.startswith("-")
            field = order_by[1:] if reverse else order_by
            rows.sort(key=lambda r: r.get(field, ""), reverse=reverse)

        if limit is not None:
            rows = rows[:limit]

        if columns is not None:
            rows = [{"_key": r["_key"], **{c: r.get(c) for c in columns}} for r in rows]

        return rows

    def query(self, prefix="", where=None, columns=None, order_by=None,
              limit=None, skip_invalid=False):
        """
        SQL-like query over keys sharing a prefix.

        Args:
            prefix:       Key prefix to filter on (e.g. "user:").
            where:        Callable predicate applied to each value dict.
                          e.g. where=lambda v: v['age'] > 25
            columns:      List of fields to include in results. None returns all fields.
                          '_key' is always included.
            order_by:     Field name to sort by. Prefix with '-' for descending.
                          e.g. order_by='-age'
            limit:        Maximum number of results to return.
            skip_invalid: If True, silently skip non-dict values instead of raising.

        Returns:
            List of dicts. Each dict includes '_key' plus requested fields.

        Raises:
            TypeError: If a value is not a dict and skip_invalid is False.

        Example:
            db.query("user:",
                where=lambda v: v['city'] == 'NYC',
                columns=['name', 'age'],
                order_by='-age',
                limit=5)
        """
        now = time.time()
        if self._in_transaction:
            return self._query_rows(prefix, where, columns, order_by, limit, skip_invalid, now)
        with self._lock():
            self._reload()
            return self._query_rows(prefix, where, columns, order_by, limit, skip_invalid, now)

    def update_where(self, prefix="", where=None, updates=None):
        """
        Bulk update all keys under prefix matching a predicate.

        Args:
            prefix:  Key prefix to filter on.
            where:   Callable predicate applied to each value dict.
                     None matches all keys under prefix.
            updates: Dict of fields to merge into matching records.

        Returns:
            Number of records updated.

        Raises:
            ValueError: If updates is None or empty.
            TypeError:  If a value under prefix is not a dict.

        Example:
            db.update_where("user:",
                where=lambda v: v['city'] == 'NYC',
                updates={'active': True})
        """
        if not updates:
            raise ValueError("updates must be a non-empty dict")

        now = time.time()

        def _apply(data):
            count = 0
            for k, entry in data.items():
                if not k.startswith(prefix):
                    continue
                if entry.get("exp") is not None and now > entry["exp"]:
                    continue
                v = entry["v"]
                if not isinstance(v, dict):
                    raise TypeError(
                        f"update_where() requires dict values - key '{k}' has type "
                        f"{type(v).__name__}."
                    )
                if where is None or where(v):
                    entry["v"] = {**v, **updates}
                    count += 1
            return count

        if self._in_transaction:
            return _apply(self.data)
        with self._lock():
            self._reload()
            count = _apply(self.data)
            if count:
                self._save()
        return count

    def delete_where(self, prefix="", where=None):
        """
        Bulk delete all keys under prefix matching a predicate.

        Args:
            prefix: Key prefix to filter on.
            where:  Callable predicate applied to each value dict.
                    None deletes all keys under prefix.

        Returns:
            Number of records deleted.

        Raises:
            TypeError: If a value under prefix is not a dict.

        Example:
            db.delete_where("session:", where=lambda v: v['expired'] == True)
        """
        now = time.time()

        def _collect(data):
            to_delete = []
            for k, entry in data.items():
                if not k.startswith(prefix):
                    continue
                if entry.get("exp") is not None and now > entry["exp"]:
                    continue
                v = entry["v"]
                if not isinstance(v, dict):
                    raise TypeError(
                        f"delete_where() requires dict values - key '{k}' has type "
                        f"{type(v).__name__}."
                    )
                if where is None or where(v):
                    to_delete.append(k)
            return to_delete

        if self._in_transaction:
            to_delete = _collect(self.data)
            for k in to_delete:
                self.data.pop(k)
            return len(to_delete)
        with self._lock():
            self._reload()
            to_delete = _collect(self.data)
            for k in to_delete:
                self.data.pop(k)
            if to_delete:
                self._save()
        return len(to_delete)

    def count(self):
        return len(self.keys())

    def compact(self):
        if self._in_transaction:
            now = time.time()
            expired = [k for k, v in self.data.items()
                       if v.get("exp") is not None and now > v["exp"]]
            for k in expired:
                self.data.pop(k)
            return len(self.data)
        with self._lock():
            self._reload()
            now = time.time()
            expired = [k for k, v in self.data.items()
                       if v.get("exp") is not None and now > v["exp"]]
            for k in expired:
                self.data.pop(k)
            self._save()
        return len(self.data)





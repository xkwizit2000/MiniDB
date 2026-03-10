#!/usr/bin/env python3
"""minidb - Tiny key-value database backed by JSON.

One file. Zero deps. Stores stuff.

Usage:
  minidb.py set mykey "hello world"
  minidb.py get mykey                    → hello world
  minidb.py del mykey
  minidb.py list                         → all keys
  minidb.py list --prefix user:          → filtered keys
  minidb.py search "hello"              → search values
  minidb.py export                       → dump all as JSON
  minidb.py import data.json             → import from JSON
  minidb.py stats                        → database stats
  minidb.py -f custom.db set key val     → custom db file
"""

import argparse
import fnmatch
import json
import os
import sys
import time
from datetime import datetime


DEFAULT_DB = os.path.expanduser("~/.minidb.json")


class MiniDB:
    def __init__(self, path: str):
        self.path = path
        self.data = self._load()

    def _load(self) -> dict:
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.data, f, indent=2, default=str)
        os.replace(tmp, self.path)

    def set(self, key: str, value: str, ttl: int = 0):
        entry = {"value": value, "updated": time.time()}
        if ttl > 0:
            entry["expires"] = time.time() + ttl
        self.data[key] = entry
        self._save()

    def get(self, key: str) -> str | None:
        entry = self.data.get(key)
        if not entry:
            return None
        if "expires" in entry and entry["expires"] < time.time():
            del self.data[key]
            self._save()
            return None
        return entry.get("value")

    def delete(self, key: str) -> bool:
        if key in self.data:
            del self.data[key]
            self._save()
            return True
        return False

    def keys(self, prefix: str = "", pattern: str = "") -> list[str]:
        self._gc()
        keys = list(self.data.keys())
        if prefix:
            keys = [k for k in keys if k.startswith(prefix)]
        if pattern:
            keys = [k for k in keys if fnmatch.fnmatch(k, pattern)]
        return sorted(keys)

    def search(self, query: str) -> list[tuple[str, str]]:
        self._gc()
        results = []
        q = query.lower()
        for key, entry in self.data.items():
            val = str(entry.get("value", ""))
            if q in key.lower() or q in val.lower():
                results.append((key, val))
        return results

    def _gc(self):
        """Remove expired entries."""
        now = time.time()
        expired = [k for k, v in self.data.items() if "expires" in v and v["expires"] < now]
        for k in expired:
            del self.data[k]
        if expired:
            self._save()

    def stats(self) -> dict:
        self._gc()
        total = len(self.data)
        size = os.path.getsize(self.path) if os.path.exists(self.path) else 0
        with_ttl = sum(1 for v in self.data.values() if "expires" in v)
        return {"keys": total, "size_bytes": size, "with_ttl": with_ttl, "path": self.path}

    def export_all(self) -> dict:
        self._gc()
        return {k: v.get("value") for k, v in self.data.items()}

    def import_data(self, data: dict):
        for k, v in data.items():
            self.set(k, v if isinstance(v, str) else json.dumps(v))


def main():
    parser = argparse.ArgumentParser(description="Tiny key-value database")
    parser.add_argument("-f", "--file", default=DEFAULT_DB, help="Database file")
    sub = parser.add_subparsers(dest="command")

    s = sub.add_parser("set", help="Set key-value")
    s.add_argument("key")
    s.add_argument("value")
    s.add_argument("--ttl", type=int, default=0, help="TTL in seconds")

    g = sub.add_parser("get", help="Get value")
    g.add_argument("key")

    d = sub.add_parser("del", help="Delete key")
    d.add_argument("key")

    l = sub.add_parser("list", help="List keys")
    l.add_argument("--prefix", "-p", default="")
    l.add_argument("--pattern", default="")

    sr = sub.add_parser("search", help="Search keys/values")
    sr.add_argument("query")

    sub.add_parser("export", help="Export all as JSON")

    im = sub.add_parser("import", help="Import from JSON file")
    im.add_argument("file")

    sub.add_parser("stats", help="Database statistics")

    sub.add_parser("gc", help="Remove expired entries")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1

    db = MiniDB(args.file)

    if args.command == "set":
        db.set(args.key, args.value, args.ttl)
        print(f"Set {args.key}")
    elif args.command == "get":
        val = db.get(args.key)
        if val is None:
            print(f"Key not found: {args.key}", file=sys.stderr)
            return 1
        print(val)
    elif args.command == "del":
        if db.delete(args.key):
            print(f"Deleted {args.key}")
        else:
            print(f"Key not found: {args.key}", file=sys.stderr)
            return 1
    elif args.command == "list":
        for k in db.keys(args.prefix, args.pattern):
            print(f"  {k}")
    elif args.command == "search":
        for k, v in db.search(args.query):
            print(f"  {k}: {v[:80]}")
    elif args.command == "export":
        print(json.dumps(db.export_all(), indent=2))
    elif args.command == "import":
        with open(args.file) as f:
            data = json.load(f)
        db.import_data(data)
        print(f"Imported {len(data)} entries")
    elif args.command == "stats":
        s = db.stats()
        print(f"  Keys:     {s['keys']}")
        print(f"  Size:     {s['size_bytes']:,} bytes")
        print(f"  With TTL: {s['with_ttl']}")
        print(f"  Path:     {s['path']}")
    elif args.command == "gc":
        db._gc()
        print("GC complete")

    return 0


if __name__ == "__main__":
    sys.exit(main())

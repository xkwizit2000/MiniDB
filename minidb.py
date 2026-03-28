#!/usr/bin/env python3
"""Minimal embedded key-value database with persistence — zero-dep."""
import json, os, hashlib, time

class MiniDB:
    def __init__(self, path="minidb.json"):
        self.path=path; self.data={}; self._load()
    def _load(self):
        if os.path.exists(self.path):
            with open(self.path) as f: self.data=json.load(f)
    def _save(self):
        with open(self.path,"w") as f: json.dump(self.data,f)
    def put(self, key, value): self.data[key]={"v":value,"ts":time.time()}; self._save()
    def get(self, key): e=self.data.get(key); return e["v"] if e else None
    def delete(self, key): self.data.pop(key,None); self._save()
    def keys(self): return list(self.data.keys())
    def scan(self, prefix=""): return {k:v["v"] for k,v in self.data.items() if k.startswith(prefix)}
    def count(self): return len(self.data)
    def compact(self):
        """Remove tombstones and rewrite."""
        self._save(); return len(self.data)

if __name__=="__main__":
    import tempfile; path=os.path.join(tempfile.mkdtemp(),"test.json")
    db=MiniDB(path)
    db.put("user:1",{"name":"Alice","age":30}); db.put("user:2",{"name":"Bob","age":25})
    db.put("config:theme","dark")
    print(f"user:1 = {db.get('user:1')}"); print(f"Count: {db.count()}")
    print(f"Scan 'user:': {db.scan('user:')}")
    db.delete("user:2"); print(f"After delete: {db.keys()}")
    # Persistence test
    db2=MiniDB(path); print(f"Reloaded: {db2.get('user:1')}")

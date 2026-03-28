#!/usr/bin/env python3
"""Minimal in-memory database with SQL-like queries."""
import sys, json, re, operator

class MiniDB:
    def __init__(self): self.tables = {}
    def create(self, name, columns):
        self.tables[name] = {'columns': columns, 'rows': [], 'auto_id': 1}
    def insert(self, table, values):
        t = self.tables[table]
        row = {'_id': t['auto_id']}
        row.update(dict(zip(t['columns'], values)))
        t['rows'].append(row); t['auto_id'] += 1
        return row['_id']
    def select(self, table, columns=None, where=None, order_by=None, limit=None):
        t = self.tables[table]; rows = t['rows']
        if where: rows = [r for r in rows if where(r)]
        if order_by:
            key, rev = (order_by[1:], True) if order_by.startswith('-') else (order_by, False)
            rows = sorted(rows, key=lambda r: r.get(key, ''), reverse=rev)
        if limit: rows = rows[:limit]
        if columns: rows = [{c: r.get(c) for c in columns} for r in rows]
        return rows
    def update(self, table, where, updates):
        count = 0
        for r in self.tables[table]['rows']:
            if where(r): r.update(updates); count += 1
        return count
    def delete(self, table, where):
        t = self.tables[table]; before = len(t['rows'])
        t['rows'] = [r for r in t['rows'] if not where(r)]
        return before - len(t['rows'])
    def save(self, path): json.dump(self.tables, open(path, 'w'), indent=2)
    def load(self, path): self.tables = json.load(open(path))

if __name__ == '__main__':
    db = MiniDB()
    db.create('users', ['name', 'age', 'city'])
    for n, a, c in [('Alice',30,'NYC'),('Bob',25,'SF'),('Charlie',35,'NYC'),('Diana',28,'LA'),('Eve',32,'SF')]:
        db.insert('users', [n, a, c])
    print("All users:")
    for r in db.select('users'): print(f"  {r}")
    print(f"\nNYC users over 29:")
    for r in db.select('users', where=lambda r: r['city']=='NYC' and r['age']>29):
        print(f"  {r}")
    print(f"\nBy age desc, top 3:")
    for r in db.select('users', columns=['name','age'], order_by='-age', limit=3):
        print(f"  {r}")
    db.update('users', lambda r: r['name']=='Bob', {'age': 26})
    print(f"\nBob updated: {db.select('users', where=lambda r: r['name']=='Bob')}")
    db.save('/tmp/minidb_test.json')
    print(f"\nSaved to /tmp/minidb_test.json")

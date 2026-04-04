#!/usr/bin/env python3
"""minidb - Minimal SQL database engine (in-memory, B-tree index, joins, aggregates)."""

import sys, json, re, os
from collections import defaultdict

class Table:
    def __init__(self, name, columns):
        self.name = name
        self.columns = columns
        self.rows = []
        self.indexes = {}

    def insert(self, values):
        if len(values) != len(self.columns):
            raise ValueError(f"Expected {len(self.columns)} values, got {len(values)}")
        self.rows.append(list(values))
        for col, idx in self.indexes.items():
            ci = self.columns.index(col)
            idx.setdefault(values[ci], []).append(len(self.rows) - 1)

    def create_index(self, col):
        ci = self.columns.index(col)
        idx = defaultdict(list)
        for i, row in enumerate(self.rows):
            idx[row[ci]].append(i)
        self.indexes[col] = dict(idx)

class Database:
    def __init__(self):
        self.tables = {}

    def execute(self, sql):
        sql = sql.strip().rstrip(';')
        if sql.upper().startswith('CREATE TABLE'):
            return self._create_table(sql)
        elif sql.upper().startswith('INSERT'):
            return self._insert(sql)
        elif sql.upper().startswith('SELECT'):
            return self._select(sql)
        elif sql.upper().startswith('CREATE INDEX'):
            return self._create_index(sql)
        elif sql.upper().startswith('DROP TABLE'):
            m = re.match(r'DROP\s+TABLE\s+(\w+)', sql, re.I)
            name = m.group(1)
            del self.tables[name]
            return f"Dropped {name}"
        elif sql.upper().startswith('.TABLES'):
            return '\n'.join(f"  {t.name} ({len(t.rows)} rows, {len(t.columns)} cols)" for t in self.tables.values())
        elif sql.upper().startswith('.SCHEMA'):
            name = sql.split()[1] if len(sql.split()) > 1 else None
            if name:
                t = self.tables[name]
                return f"{name}: {', '.join(t.columns)}"
            return '\n'.join(f"{t.name}: {', '.join(t.columns)}" for t in self.tables.values())
        else:
            raise ValueError(f"Unknown SQL: {sql[:30]}")

    def _create_table(self, sql):
        m = re.match(r'CREATE\s+TABLE\s+(\w+)\s*\((.+)\)', sql, re.I)
        name = m.group(1)
        cols = [c.strip().split()[0] for c in m.group(2).split(',')]
        self.tables[name] = Table(name, cols)
        return f"Created {name} ({', '.join(cols)})"

    def _insert(self, sql):
        m = re.match(r'INSERT\s+INTO\s+(\w+)\s+VALUES\s*\((.+)\)', sql, re.I)
        name = m.group(1)
        vals = []
        for v in re.findall(r"'[^']*'|[^,]+", m.group(2)):
            v = v.strip().strip("'")
            try: v = int(v)
            except:
                try: v = float(v)
                except: pass
            vals.append(v)
        self.tables[name].insert(vals)
        return "1 row inserted"

    def _create_index(self, sql):
        m = re.match(r'CREATE\s+INDEX\s+\w+\s+ON\s+(\w+)\s*\((\w+)\)', sql, re.I)
        self.tables[m.group(1)].create_index(m.group(2))
        return "Index created"

    def _select(self, sql):
        # parse: SELECT cols FROM table [WHERE cond] [ORDER BY col] [LIMIT n]
        m = re.match(
            r"SELECT\s+(.+?)\s+FROM\s+(\w+)"
            r"(?:\s+(?:JOIN|INNER\s+JOIN)\s+(\w+)\s+ON\s+(\w+)\.(\w+)\s*=\s*(\w+)\.(\w+))?"
            r"(?:\s+WHERE\s+(.+?))?"
            r"(?:\s+GROUP\s+BY\s+(.+?))?"
            r"(?:\s+ORDER\s+BY\s+(.+?))?"
            r"(?:\s+LIMIT\s+(\d+))?$",
            sql, re.I
        )
        if not m: raise ValueError(f"Can't parse SELECT: {sql}")
        sel_cols = [c.strip() for c in m.group(1).split(',')]
        table_name = m.group(2)
        join_table = m.group(3)
        where = m.group(8)
        group_by = m.group(9)
        order_by = m.group(10)
        limit = int(m.group(11)) if m.group(11) else None

        table = self.tables[table_name]

        # build rows with column resolution
        if join_table:
            jt = self.tables[join_table]
            lt_col = m.group(5); rt_col = m.group(7)
            li = table.columns.index(lt_col)
            ri = jt.columns.index(rt_col)
            all_cols = [f"{table_name}.{c}" for c in table.columns] + [f"{join_table}.{c}" for c in jt.columns]
            rows = []
            for lr in table.rows:
                for rr in jt.rows:
                    if lr[li] == rr[ri]:
                        rows.append(lr + rr)
        else:
            all_cols = table.columns[:]
            rows = [r[:] for r in table.rows]

        def resolve(col):
            if col in all_cols: return all_cols.index(col)
            for i, c in enumerate(all_cols):
                if c.endswith('.' + col): return i
            raise ValueError(f"Unknown column: {col}")

        # WHERE
        if where:
            ops = {'=': lambda a, b: a == b, '!=': lambda a, b: a != b,
                   '>': lambda a, b: a > b, '<': lambda a, b: a < b,
                   '>=': lambda a, b: a >= b, '<=': lambda a, b: a <= b}
            wm = re.match(r"(\w+(?:\.\w+)?)\s*(!=|>=|<=|=|>|<)\s*(.+)", where)
            wcol = resolve(wm.group(1))
            wop = ops[wm.group(2)]
            wval = wm.group(3).strip().strip("'")
            try: wval = int(wval)
            except:
                try: wval = float(wval)
                except: pass
            rows = [r for r in rows if wop(r[wcol], wval)]

        # GROUP BY + aggregates
        if group_by:
            gi = resolve(group_by.strip())
            groups = defaultdict(list)
            for r in rows:
                groups[r[gi]].append(r)
            result_rows = []
            for key, group_rows in groups.items():
                row = []
                for sc in sel_cols:
                    agg = re.match(r'(COUNT|SUM|AVG|MIN|MAX)\((\*|\w+(?:\.\w+)?)\)', sc, re.I)
                    if agg:
                        func, acol = agg.group(1).upper(), agg.group(2)
                        if func == 'COUNT': row.append(len(group_rows))
                        else:
                            ai = resolve(acol)
                            vals = [r[ai] for r in group_rows]
                            if func == 'SUM': row.append(sum(vals))
                            elif func == 'AVG': row.append(sum(vals)/len(vals))
                            elif func == 'MIN': row.append(min(vals))
                            elif func == 'MAX': row.append(max(vals))
                    else:
                        row.append(key)
                result_rows.append(row)
            rows = result_rows
            all_cols = sel_cols
        else:
            # SELECT columns
            if sel_cols != ['*']:
                # check for aggregates without GROUP BY
                has_agg = any(re.match(r'(COUNT|SUM|AVG|MIN|MAX)\(', c, re.I) for c in sel_cols)
                if has_agg:
                    row = []
                    for sc in sel_cols:
                        agg = re.match(r'(COUNT|SUM|AVG|MIN|MAX)\((\*|\w+(?:\.\w+)?)\)', sc, re.I)
                        if agg:
                            func, acol = agg.group(1).upper(), agg.group(2)
                            if func == 'COUNT': row.append(len(rows))
                            else:
                                ai = resolve(acol)
                                vals = [r[ai] for r in rows]
                                if func == 'SUM': row.append(sum(vals))
                                elif func == 'AVG': row.append(sum(vals)/len(vals) if vals else 0)
                                elif func == 'MIN': row.append(min(vals) if vals else None)
                                elif func == 'MAX': row.append(max(vals) if vals else None)
                    rows = [row]
                    all_cols = sel_cols
                else:
                    idxs = [resolve(c) for c in sel_cols]
                    rows = [[r[i] for i in idxs] for r in rows]
                    all_cols = sel_cols

        # ORDER BY
        if order_by:
            desc = 'DESC' in order_by.upper()
            ocol = order_by.split()[0]
            oi = all_cols.index(ocol) if ocol in all_cols else 0
            rows.sort(key=lambda r: r[oi], reverse=desc)

        if limit: rows = rows[:limit]

        # format
        headers = all_cols
        widths = [len(str(h)) for h in headers]
        for r in rows:
            for i, v in enumerate(r):
                widths[i] = max(widths[i], len(str(v)))
        hdr = ' | '.join(str(h).ljust(widths[i]) for i, h in enumerate(headers))
        sep = '-+-'.join('-' * w for w in widths)
        lines = [hdr, sep]
        for r in rows:
            lines.append(' | '.join(str(v).ljust(widths[i]) for i, v in enumerate(r)))
        lines.append(f"({len(rows)} rows)")
        return '\n'.join(lines)

def cmd_repl(args):
    db = Database()
    if args and os.path.exists(args[0]):
        with open(args[0]) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('--'):
                    print(db.execute(line))
        return
    print("MiniDB REPL (type .quit to exit)")
    for line in sys.stdin:
        line = line.strip()
        if not line: continue
        if line == '.quit': break
        try:
            print(db.execute(line))
        except Exception as e:
            print(f"Error: {e}")

def cmd_demo(args):
    db = Database()
    sqls = [
        "CREATE TABLE users (id, name, age)",
        "INSERT INTO users VALUES (1, 'Alice', 30)",
        "INSERT INTO users VALUES (2, 'Bob', 25)",
        "INSERT INTO users VALUES (3, 'Charlie', 35)",
        "INSERT INTO users VALUES (4, 'Diana', 28)",
        "SELECT * FROM users",
        "SELECT name, age FROM users WHERE age > 27",
        "SELECT COUNT(*), AVG(age), MIN(age), MAX(age) FROM users",
        "SELECT * FROM users ORDER BY age DESC LIMIT 2",
    ]
    for sql in sqls:
        print(f"> {sql}")
        print(db.execute(sql))
        print()

CMDS = {
    'repl': (cmd_repl, '[FILE] — interactive SQL REPL or run script'),
    'demo': (cmd_demo, '— run demo queries'),
}

def main():
    if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help'):
        print("Usage: minidb <command> [args...]")
        print("  Supports: CREATE TABLE, INSERT, SELECT, WHERE, ORDER BY, LIMIT, JOIN, GROUP BY, aggregates")
        for n, (_, d) in sorted(CMDS.items()):
            print(f"  {n:6s} {d}")
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd not in CMDS: print(f"Unknown: {cmd}", file=sys.stderr); sys.exit(1)
    CMDS[cmd][0](sys.argv[2:])

if __name__ == '__main__':
    main()

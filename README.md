# MiniDB

![Version](https://img.shields.io/badge/version-0.6.0-blue)
![License](https://img.shields.io/badge/license-MIT-green)

A lightweight, zero-dependency key-value store backed by JSON. Single file, production-grade primitives.

Forked from [rogue-agent1/minidb](https://github.com/rogue-agent1/minidb).

## Features

- **TTL support** - per-key expiry with lazy cleanup and `compact()`
- **Atomic writes** - crash-safe via temp file + `os.replace()`
- **File locking** - safe for concurrent processes (`fcntl` on Unix, `msvcrt` on Windows, sentinel fallback)
- **Transactions** - atomic multi-op blocks with full rollback on failure
- **Write buffering** - optional interval or op-count flushing for high-throughput workloads
- **SQL-like queries** - `query()`, `update_where()`, `delete_where()` with `where`, `order_by`, `limit`, and column projection
- **Query builder** - `Q` objects with 12 operators, AND/OR/NOT combinators, no lambdas required
- **Batch operations** - `put_many`, `get_many`, `delete_many` with a single write per batch
- **Prefix scan** - namespace your keys and query by prefix
- **Stored `None`** - distinguishes a missing key from a key with a `None` value
- **Zero dependencies** - stdlib only (`json`, `os`, `time`, `tempfile`, `threading`, `fcntl`/`msvcrt`)

## Installation

No install needed. Copy `minidb.py` into your project.

## Usage

### Basic Operations

```python
from minidb import MiniDB

db = MiniDB("mydb.json")

db.put("user:1", {"name": "Alice", "age": 30})
db.get("user:1")                        # {"name": "Alice", "age": 30}
db.get("missing", default="fallback")   # "fallback"
db.exists("user:1")                     # True
db.delete("user:1")
db.keys()                               # all non-expired keys
db.count()                              # number of non-expired keys
```

### TTL

```python
# Expires in 5 minutes
db.put("session:abc", {"token": "xyz"}, ttl=300)

# Storing None - distinguishable from a missing key
db.put("flag", None)
db.get("flag")      # None
db.exists("flag")   # True

# Purge all expired keys and rewrite file
db.compact()
```

### Batch Operations

```python
# Single disk write per call
db.put_many({"a": 1, "b": 2, "c": 3})
db.put_many([("x", 10, 60), ("y", 20, 120)])   # per-item TTL
db.get_many(["a", "b", "missing"])              # {"a": 1, "b": 2}
db.delete_many(["a", "b"])
```

### Prefix Scan

```python
db.put_many({
    "user:1": {"name": "Alice"},
    "user:2": {"name": "Bob"},
    "config:theme": "dark",
})
db.scan("user:")    # {"user:1": {...}, "user:2": {...}}
```

### Query Builder (Q objects)

```python
from minidb import MiniDB, Q

db = MiniDB("mydb.json")

# Comparison operators
db.query("user:", where=Q(city="NYC"))           # equality (implicit eq)
db.query("user:", where=Q(city__eq="NYC"))       # equality (explicit)
db.query("user:", where=Q(age__gt=29))           # greater than
db.query("user:", where=Q(age__gte=30))          # greater than or equal
db.query("user:", where=Q(age__lt=30))           # less than
db.query("user:", where=Q(age__lte=30))          # less than or equal
db.query("user:", where=Q(city__ne="LA"))        # not equal

# Membership operators
db.query("user:", where=Q(city__in=["NYC", "SF"]))   # value in list
db.query("user:", where=Q(city__nin=["LA"]))          # value not in list

# String operators
db.query("user:", where=Q(name__contains="li"))       # substring match
db.query("user:", where=Q(name__startswith="A"))      # prefix match
db.query("user:", where=Q(name__endswith="e"))        # suffix match

# Existence operators
db.query("user:", where=Q(nickname__exists=True))     # field present
db.query("user:", where=Q(nickname__exists=False))    # field absent
db.query("user:", where=Q(nickname__isnull=True))     # field is None
db.query("user:", where=Q(nickname__isnull=False))    # field is not None

# Combinators - AND, OR, NOT
db.query("user:", where=Q(city="NYC") & Q(age__gt=29))
db.query("user:", where=Q(city="NYC") | Q(city="SF"))
db.query("user:", where=~Q(city="LA"))

# Complex combinations
db.query("user:",
    where=(Q(city="NYC") | Q(city="SF")) & Q(age__gte=30),
    order_by='-age',
    limit=5)

# Q works with update_where and delete_where too
db.update_where("user:", where=Q(city="NYC") & Q(age__gt=30), updates={'flagged': True})
db.delete_where("user:", where=Q(score__lt=75))
```

### SQL-like Queries

```python
db.put_many({
    "user:1": {"name": "Alice",   "age": 30, "city": "NYC"},
    "user:2": {"name": "Bob",     "age": 25, "city": "SF"},
    "user:3": {"name": "Charlie", "age": 35, "city": "NYC"},
    "user:4": {"name": "Diana",   "age": 28, "city": "LA"},
    "user:5": {"name": "Eve",     "age": 32, "city": "SF"},
})

# All records under a prefix - returns list of dicts, each with '_key'
db.query("user:")

# Filter with a where predicate
db.query("user:", where=lambda v: v['city'] == 'NYC')

# Column projection - '_key' always included
db.query("user:", columns=['name', 'age'])

# Sort ascending or descending (prefix '-' for desc)
db.query("user:", order_by='age')
db.query("user:", order_by='-age')

# Limit results
db.query("user:", order_by='-age', limit=3)

# Full SQL-style query
db.query("user:",
    where=lambda v: v['age'] >= 30,
    columns=['name', 'age'],
    order_by='-age',
    limit=5)
# [{'_key': 'user:3', 'name': 'Charlie', 'age': 35},
#  {'_key': 'user:5', 'name': 'Eve',     'age': 32},
#  {'_key': 'user:1', 'name': 'Alice',   'age': 30}]

# Bulk update all matching records - single disk write
db.update_where("user:",
    where=lambda v: v['city'] == 'NYC',
    updates={'active': True})

# Bulk delete all matching records - single disk write
db.delete_where("user:", where=lambda v: v['active'] == False)

# Non-dict values raise TypeError by default
# Pass skip_invalid=True to skip them silently instead
db.query("user:", skip_invalid=True)
```

### Transactions

```python
# All ops commit atomically, or none if an exception occurs
with db.transaction():
    db.put("account:alice", 900)
    db.put("account:bob", 1100)

# Rollback on failure - nothing written to disk
try:
    with db.transaction():
        db.put("x", "new_value")
        raise ValueError("something went wrong")
except ValueError:
    pass
db.get("x")   # original value - rollback succeeded

# All ops work inside transactions including query, update_where, delete_where
with db.transaction():
    db.update_where("user:", where=lambda v: v['city'] == 'NYC', updates={'notified': True})
    db.delete_where("session:", where=lambda v: v['expired'] == True)
```

### Write Buffering

```python
# Flush every 5 seconds
db = MiniDB("mydb.json", flush_interval=5)

# Flush every 100 mutations
db = MiniDB("mydb.json", flush_ops=100)

# Whichever threshold is hit first
db = MiniDB("mydb.json", flush_interval=5, flush_ops=100)

db.put("a", 1)  # held in memory, not written to disk yet
db.flush()      # force immediate write
db.close()      # flush remaining buffer and stop timer (auto-called on exit)
```

## Running Tests

```bash
python -m unittest test_minidb -v
```

114 tests across basic ops, persistence, TTL, batch ops, prefix scan, concurrency, transactions, write buffering, SQL-like queries, and Q query builder.

## License

MIT - see [LICENSE](LICENSE).  
Based on [rogue-agent1/minidb](https://github.com/rogue-agent1/minidb).

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

# Changelog

All notable changes to this project will be documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [0.5.0] - 2026-04-05

Inspired by the `select()`, `update()`, and `order_by` conventions from [rogue-agent1/minidb-engine](https://github.com/rogue-agent1/minidb-engine), with schema validation done properly.

### Added
- `query(prefix, where, columns, order_by, limit, skip_invalid)` - SQL-like queries over key namespaces
  - `where=lambda v: ...` - predicate filtering on value dicts
  - `order_by='field'` / `order_by='-field'` - ascending/descending sort (Django convention)
  - `columns=['a', 'b']` - field projection; `_key` always included in results
  - `limit=N` - cap results after sort
  - `skip_invalid=True` - silently skip non-dict values; raises `TypeError` by default
  - Works inside transactions, respects TTL expiry
- `update_where(prefix, where, updates)` - predicate-based bulk update with single disk write
  - `where=None` matches all keys under prefix
  - Raises `ValueError` on empty updates, `TypeError` on non-dict values
  - Full transaction and rollback support
- `delete_where(prefix, where)` - predicate-based bulk delete with single disk write
  - `where=None` deletes all keys under prefix
  - Full transaction and rollback support
- 30 new tests covering all query combinations, update/delete predicates, transaction participation, rollback, and error handling

---

## [0.4.0] - 2026-04-05

### Added
- Write buffering with flush interval - optional `flush_interval` and `flush_ops` parameters on `MiniDB()`
  - `flush_interval=N` flushes to disk every N seconds via a daemon `threading.Timer`
  - `flush_ops=N` flushes after every N mutations, whichever threshold is hit first
  - `db.flush()` - manual immediate flush
  - `db.close()` - flushes remaining buffer and stops the timer; registered via `atexit` automatically
  - Default behavior (no params) unchanged - writes remain synchronous and immediate
  - Fully compatible with transactions - transaction commits bypass the buffer and flush directly
- 9 new tests covering interval flush, op-count flush, manual flush, close-on-exit, counter reset, and transaction compatibility

---

## [0.3.0] - 2026-04-03

### Added
- `transaction()` context manager - groups multiple operations into a single atomic commit
  - All writes held in memory during the block, flushed in one `_save()` on success
  - Full rollback to pre-transaction state on any exception - nothing written to disk
  - File lock held for the entire transaction duration
  - All existing ops (`put`, `get`, `delete`, `scan`, etc.) work inside transactions
  - Nested transactions raise `RuntimeError`
- 9 new tests covering commit, rollback, single-write guarantee, TTL inside transactions, persistence after reload, and nested transaction guard

---

## [0.2.0] - 2026-04-03

Forked from [rogue-agent1/minidb](https://github.com/rogue-agent1/minidb).

### Added
- TTL support - `put(key, value, ttl=seconds)` with lazy expiry on `get()`
- Atomic writes - temp file + `os.replace()` prevents corruption on crash
- File locking - `fcntl` (Unix), `msvcrt` (Windows), sentinel file fallback
- `put_many()` - batch insert from dict, list of tuples, or list of 3-tuples with per-item TTL
- `get_many()` - batch fetch, missing and expired keys silently omitted
- `delete_many()` - batch delete with single disk write
- `get(key, default=...)` - optional default value for missing keys
- `exists(key)` - explicit key existence check
- `compact()` - purge all expired keys and rewrite file
- `__version__` - version string accessible as `minidb.__version__`
- MIT License
- Test suite - 40 tests across basic ops, persistence, TTL, batch ops, scan, concurrency

### Fixed
- `delete()` was not calling `_save()` - deletes were lost on restart
- `compact()` was not removing expired keys - now actually purges them
- Storing `None` as a value was indistinguishable from a missing key - fixed via `_MISSING` sentinel

---

## [0.1.0] - upstream

Original implementation by [rogue-agent1](https://github.com/rogue-agent1/minidb).

- JSON-backed key-value store
- `put`, `get`, `delete`, `keys`, `scan`, `count`


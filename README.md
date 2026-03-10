# minidb

Tiny key-value database backed by JSON.

One file. Zero deps. Stores stuff.

## Usage

```bash
python3 minidb.py set mykey "hello world"
python3 minidb.py get mykey
python3 minidb.py del mykey
python3 minidb.py list --prefix user:
python3 minidb.py search "hello"
python3 minidb.py set cache:token "abc" --ttl 3600  # expires in 1h
python3 minidb.py export > backup.json
python3 minidb.py import backup.json
python3 minidb.py stats
```

Data stored in `~/.minidb.json` (override with `-f`). Atomic writes, TTL support, auto-GC.

## Requirements

Python 3.8+. No dependencies.

## License

MIT

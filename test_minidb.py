# test_minidb.py
#
# MIT License
# Copyright (c) 2026 John (JT) Thornton
# See LICENSE file for full license text.

import unittest, threading, os, time, tempfile
from minidb import MiniDB


def _db(tmp_dir, name="test.json", **kwargs):
    """Helper: create a MiniDB in a temp directory."""
    return MiniDB(os.path.join(tmp_dir, name), **kwargs)


class TestBasicOps(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = _db(self.tmp)

    def tearDown(self):
        for f in os.listdir(self.tmp):
            os.remove(os.path.join(self.tmp, f))

    def test_put_and_get(self):
        self.db.put("k", "v")
        self.assertEqual(self.db.get("k"), "v")

    def test_get_missing_returns_none(self):
        self.assertIsNone(self.db.get("no_such_key"))

    def test_overwrite(self):
        self.db.put("k", "v1")
        self.db.put("k", "v2")
        self.assertEqual(self.db.get("k"), "v2")

    def test_delete(self):
        self.db.put("k", "v")
        self.db.delete("k")
        self.assertIsNone(self.db.get("k"))

    def test_delete_missing_no_error(self):
        self.db.delete("ghost")

    def test_exists_true(self):
        self.db.put("k", "v")
        self.assertTrue(self.db.exists("k"))

    def test_exists_false(self):
        self.assertFalse(self.db.exists("nope"))

    def test_count(self):
        self.db.put("a", 1)
        self.db.put("b", 2)
        self.assertEqual(self.db.count(), 2)

    def test_keys(self):
        self.db.put("x", 1)
        self.db.put("y", 2)
        self.assertCountEqual(self.db.keys(), ["x", "y"])

    def test_value_types(self):
        self.db.put("int", 42)
        self.db.put("float", 3.14)
        self.db.put("list", [1, 2, 3])
        self.db.put("dict", {"a": 1})
        self.assertEqual(self.db.get("int"), 42)
        self.assertAlmostEqual(self.db.get("float"), 3.14)
        self.assertEqual(self.db.get("list"), [1, 2, 3])
        self.assertEqual(self.db.get("dict"), {"a": 1})

    def test_store_none_value(self):
        self.db.put("null_key", None)
        self.assertIsNone(self.db.get("null_key"))
        self.assertTrue(self.db.exists("null_key"))

    def test_none_value_vs_missing_key(self):
        self.db.put("null_key", None)
        self.assertTrue(self.db.exists("null_key"))
        self.assertFalse(self.db.exists("no_such_key"))

    def test_get_with_default(self):
        self.db.put("present", "v")
        self.assertEqual(self.db.get("present", "fallback"), "v")
        self.assertEqual(self.db.get("missing", "fallback"), "fallback")
        self.assertEqual(self.db.get("missing", default=0), 0)

    def test_get_default_does_not_mask_stored_none(self):
        self.db.put("null_key", None)
        self.assertIsNone(self.db.get("null_key", "fallback"))


class TestPersistence(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        for f in os.listdir(self.tmp):
            os.remove(os.path.join(self.tmp, f))

    def test_survives_reload(self):
        db1 = _db(self.tmp)
        db1.put("persist", "yes")
        db2 = _db(self.tmp)
        self.assertEqual(db2.get("persist"), "yes")

    def test_delete_survives_reload(self):
        db1 = _db(self.tmp)
        db1.put("k", "v")
        db1.delete("k")
        db2 = _db(self.tmp)
        self.assertIsNone(db2.get("k"))

    def test_atomic_write_leaves_no_tmp_files(self):
        db = _db(self.tmp)
        db.put("k", "v")
        tmp_files = [f for f in os.listdir(self.tmp) if f.endswith(".tmp")]
        self.assertEqual(tmp_files, [])


class TestTTL(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = _db(self.tmp)

    def tearDown(self):
        for f in os.listdir(self.tmp):
            os.remove(os.path.join(self.tmp, f))

    def test_no_ttl_persists(self):
        self.db.put("k", "v")
        time.sleep(0.1)
        self.assertEqual(self.db.get("k"), "v")

    def test_ttl_expires(self):
        self.db.put("k", "v", ttl=0.1)
        time.sleep(0.2)
        self.assertIsNone(self.db.get("k"))

    def test_ttl_not_yet_expired(self):
        self.db.put("k", "v", ttl=5)
        self.assertEqual(self.db.get("k"), "v")

    def test_expired_key_removed_from_disk(self):
        self.db.put("k", "v", ttl=0.1)
        time.sleep(0.2)
        self.db.get("k")
        db2 = _db(self.tmp)
        self.assertIsNone(db2.get("k"))

    def test_expired_key_excluded_from_keys(self):
        self.db.put("live", "v", ttl=5)
        self.db.put("dead", "v", ttl=0.1)
        time.sleep(0.2)
        self.assertIn("live", self.db.keys())
        self.assertNotIn("dead", self.db.keys())

    def test_expired_key_excluded_from_count(self):
        self.db.put("live", "v", ttl=5)
        self.db.put("dead", "v", ttl=0.1)
        time.sleep(0.2)
        self.assertEqual(self.db.count(), 1)

    def test_compact_purges_expired(self):
        self.db.put("live", "v", ttl=5)
        self.db.put("dead", "v", ttl=0.1)
        time.sleep(0.2)
        remaining = self.db.compact()
        self.assertEqual(remaining, 1)
        db2 = _db(self.tmp)
        self.assertIsNone(db2.get("dead"))


class TestBatchOps(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = _db(self.tmp)

    def tearDown(self):
        for f in os.listdir(self.tmp):
            os.remove(os.path.join(self.tmp, f))

    def test_put_many_dict(self):
        self.db.put_many({"a": 1, "b": 2, "c": 3})
        self.assertEqual(self.db.get("a"), 1)
        self.assertEqual(self.db.get("b"), 2)
        self.assertEqual(self.db.get("c"), 3)

    def test_put_many_tuples(self):
        self.db.put_many([("x", 10), ("y", 20)])
        self.assertEqual(self.db.get("x"), 10)
        self.assertEqual(self.db.get("y"), 20)

    def test_put_many_with_uniform_ttl(self):
        self.db.put_many({"a": 1, "b": 2}, ttl=0.1)
        time.sleep(0.2)
        self.assertIsNone(self.db.get("a"))
        self.assertIsNone(self.db.get("b"))

    def test_put_many_per_item_ttl(self):
        self.db.put_many([("live", "v", 5), ("dead", "v", 0.1)])
        time.sleep(0.2)
        self.assertEqual(self.db.get("live"), "v")
        self.assertIsNone(self.db.get("dead"))

    def test_get_many(self):
        self.db.put_many({"a": 1, "b": 2, "c": 3})
        result = self.db.get_many(["a", "c"])
        self.assertEqual(result, {"a": 1, "c": 3})

    def test_get_many_missing_omitted(self):
        self.db.put("a", 1)
        result = self.db.get_many(["a", "missing"])
        self.assertIn("a", result)
        self.assertNotIn("missing", result)

    def test_get_many_expired_omitted(self):
        self.db.put("live", "v", ttl=5)
        self.db.put("dead", "v", ttl=0.1)
        time.sleep(0.2)
        result = self.db.get_many(["live", "dead"])
        self.assertIn("live", result)
        self.assertNotIn("dead", result)

    def test_delete_many(self):
        self.db.put_many({"a": 1, "b": 2, "c": 3})
        self.db.delete_many(["a", "b"])
        self.assertIsNone(self.db.get("a"))
        self.assertIsNone(self.db.get("b"))
        self.assertEqual(self.db.get("c"), 3)

    def test_put_many_single_save(self):
        """Verify put_many writes exactly once regardless of item count."""
        save_count = {"n": 0}
        original_save = self.db._save
        def counting_save():
            save_count["n"] += 1
            original_save()
        self.db._save = counting_save
        self.db.put_many({"a": 1, "b": 2, "c": 3, "d": 4, "e": 5})
        self.assertEqual(save_count["n"], 1)


class TestScan(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = _db(self.tmp)
        self.db.put_many({
            "user:1": "alice",
            "user:2": "bob",
            "session:abc": "data",
        })

    def tearDown(self):
        for f in os.listdir(self.tmp):
            os.remove(os.path.join(self.tmp, f))

    def test_scan_prefix(self):
        result = self.db.scan("user:")
        self.assertCountEqual(result.keys(), ["user:1", "user:2"])

    def test_scan_empty_prefix_returns_all(self):
        result = self.db.scan("")
        self.assertEqual(len(result), 3)

    def test_scan_no_match(self):
        result = self.db.scan("order:")
        self.assertEqual(result, {})

    def test_scan_excludes_expired(self):
        self.db.put("user:temp", "v", ttl=0.1)
        time.sleep(0.2)
        result = self.db.scan("user:")
        self.assertNotIn("user:temp", result)


class TestConcurrency(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        for f in os.listdir(self.tmp):
            os.remove(os.path.join(self.tmp, f))

    def test_threaded_writes_no_corruption(self):
        db = _db(self.tmp)
        errors = []

        def writer(n):
            try:
                for i in range(10):
                    db.put(f"thread{n}_key{i}", i)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(n,)) for n in range(5)]
        for t in threads: t.start()
        for t in threads: t.join()

        self.assertEqual(errors, [])
        db2 = _db(self.tmp)
        self.assertIsInstance(db2.data, dict)

    def test_threaded_reads_concurrent(self):
        db = _db(self.tmp)
        db.put_many({f"k{i}": i for i in range(20)})
        errors = []

        def reader():
            try:
                for i in range(20):
                    db.get(f"k{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(errors, [])

    def test_mixed_read_write_threads(self):
        db = _db(self.tmp)
        errors = []

        def worker(n):
            try:
                for _ in range(5):
                    db.put(f"w{n}", n)
                    db.get(f"w{n}")
                    db.delete(f"w{n}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(errors, [])


class TestTransactions(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = _db(self.tmp)

    def tearDown(self):
        for f in os.listdir(self.tmp):
            os.remove(os.path.join(self.tmp, f))

    def test_transaction_commits_all(self):
        with self.db.transaction():
            self.db.put("a", 1)
            self.db.put("b", 2)
            self.db.put("c", 3)
        self.assertEqual(self.db.get("a"), 1)
        self.assertEqual(self.db.get("b"), 2)
        self.assertEqual(self.db.get("c"), 3)

    def test_transaction_single_write(self):
        """Entire transaction flushes in one _flush() call."""
        flush_count = {"n": 0}
        original_flush = self.db._flush
        def counting_flush():
            flush_count["n"] += 1
            original_flush()
        self.db._flush = counting_flush
        with self.db.transaction():
            self.db.put("a", 1)
            self.db.put("b", 2)
            self.db.put("c", 3)
        self.assertEqual(flush_count["n"], 1)

    def test_transaction_rollback_on_exception(self):
        self.db.put("x", "original")
        try:
            with self.db.transaction():
                self.db.put("x", "modified")
                self.db.put("y", "new")
                raise ValueError("simulated failure")
        except ValueError:
            pass
        self.assertEqual(self.db.get("x"), "original")
        self.assertIsNone(self.db.get("y"))

    def test_transaction_nothing_written_on_rollback(self):
        """Disk file must not change if transaction rolls back."""
        self.db.put("x", "original")
        snapshot_before = dict(self.db.data)
        try:
            with self.db.transaction():
                self.db.put("x", "modified")
                raise RuntimeError("abort")
        except RuntimeError:
            pass
        # Reload from disk and verify unchanged
        db2 = _db(self.tmp)
        self.assertEqual(db2.get("x"), "original")

    def test_transaction_rollback_restores_deletes(self):
        self.db.put("x", "keep")
        try:
            with self.db.transaction():
                self.db.delete("x")
                raise ValueError("abort")
        except ValueError:
            pass
        self.assertEqual(self.db.get("x"), "keep")

    def test_transaction_mixed_ops(self):
        self.db.put("a", 1)
        self.db.put("b", 2)
        with self.db.transaction():
            self.db.put("a", 99)
            self.db.delete("b")
            self.db.put("c", 3)
        self.assertEqual(self.db.get("a"), 99)
        self.assertIsNone(self.db.get("b"))
        self.assertEqual(self.db.get("c"), 3)

    def test_transaction_with_ttl(self):
        with self.db.transaction():
            self.db.put("short", "v", ttl=0.1)
            self.db.put("long", "v", ttl=5)
        time.sleep(0.2)
        self.assertIsNone(self.db.get("short"))
        self.assertEqual(self.db.get("long"), "v")

    def test_transaction_persists_after_reload(self):
        with self.db.transaction():
            self.db.put("a", 1)
            self.db.put("b", 2)
        db2 = _db(self.tmp)
        self.assertEqual(db2.get("a"), 1)
        self.assertEqual(db2.get("b"), 2)

    def test_nested_transaction_raises(self):
        with self.assertRaises(RuntimeError):
            with self.db.transaction():
                with self.db.transaction():
                    pass


class TestWriteBuffering(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        for f in os.listdir(self.tmp):
            os.remove(os.path.join(self.tmp, f))

    def test_default_no_buffering(self):
        """Without flush params, writes go straight to disk as before."""
        db = _db(self.tmp)
        db.put("k", "v")
        db2 = _db(self.tmp)
        self.assertEqual(db2.get("k"), "v")

    def test_buffered_write_not_on_disk_immediately(self):
        """With buffering on, put() should NOT write to disk immediately."""
        db = _db(self.tmp, flush_interval=60, flush_ops=100)
        db.put("k", "v")
        # File should not exist yet - nothing flushed
        self.assertFalse(os.path.exists(db.path))
        db.close()

    def test_manual_flush_writes_to_disk(self):
        """flush() forces an immediate write."""
        db = _db(self.tmp, flush_interval=60, flush_ops=100)
        db.put("k", "v")
        db.flush()
        db2 = _db(self.tmp)
        self.assertEqual(db2.get("k"), "v")
        db.close()

    def test_flush_on_op_count(self):
        """Hitting flush_ops threshold triggers automatic flush."""
        db = _db(self.tmp, flush_ops=3)
        db.put("a", 1)
        db.put("b", 2)
        self.assertFalse(os.path.exists(db.path))  # not yet
        db.put("c", 3)  # 3rd op - triggers flush
        self.assertTrue(os.path.exists(db.path))
        db2 = _db(self.tmp)
        self.assertEqual(db2.get("a"), 1)
        self.assertEqual(db2.get("c"), 3)
        db.close()

    def test_flush_on_interval(self):
        """Timer triggers flush after flush_interval seconds."""
        db = _db(self.tmp, flush_interval=0.2)
        db.put("k", "v")
        self.assertFalse(os.path.exists(db.path))
        time.sleep(0.4)  # wait for timer to fire
        self.assertTrue(os.path.exists(db.path))
        db2 = _db(self.tmp)
        self.assertEqual(db2.get("k"), "v")
        db.close()

    def test_close_flushes_remaining(self):
        """close() flushes any dirty data before stopping the timer."""
        db = _db(self.tmp, flush_interval=60, flush_ops=100)
        db.put("k", "v")
        db.close()
        db2 = _db(self.tmp)
        self.assertEqual(db2.get("k"), "v")

    def test_flush_ops_resets_after_flush(self):
        """Op counter resets after flush so the next batch works correctly."""
        db = _db(self.tmp, flush_ops=3)
        db.put("a", 1)
        db.put("b", 2)
        db.put("c", 3)  # flush #1
        db.put("d", 4)
        db.put("e", 5)
        db.put("f", 6)  # flush #2
        db2 = _db(self.tmp)
        self.assertEqual(db2.get("f"), 6)
        db.close()

    def test_manual_flush_noop_when_clean(self):
        """flush() on a non-dirty buffer does not error."""
        db = _db(self.tmp, flush_interval=60)
        db.flush()  # nothing dirty - should not raise
        db.close()

    def test_buffering_compatible_with_transactions(self):
        """Transactions still commit atomically when buffering is enabled."""
        db = _db(self.tmp, flush_interval=60, flush_ops=100)
        with db.transaction():
            db.put("a", 1)
            db.put("b", 2)
        # Transaction commit calls _flush directly - bypasses buffer
        db2 = _db(self.tmp)
        self.assertEqual(db2.get("a"), 1)
        self.assertEqual(db2.get("b"), 2)
        db.close()


class TestQuery(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = _db(self.tmp)
        self.db.put_many({
            "user:1": {"name": "Alice", "age": 30, "city": "NYC"},
            "user:2": {"name": "Bob",   "age": 25, "city": "SF"},
            "user:3": {"name": "Charlie","age": 35, "city": "NYC"},
            "user:4": {"name": "Diana", "age": 28, "city": "LA"},
            "user:5": {"name": "Eve",   "age": 32, "city": "SF"},
        })

    def tearDown(self):
        for f in os.listdir(self.tmp):
            os.remove(os.path.join(self.tmp, f))

    def test_query_all(self):
        results = self.db.query("user:")
        self.assertEqual(len(results), 5)

    def test_query_where(self):
        results = self.db.query("user:", where=lambda v: v['city'] == 'NYC')
        self.assertEqual(len(results), 2)
        names = {r['name'] for r in results}
        self.assertEqual(names, {"Alice", "Charlie"})

    def test_query_order_by_asc(self):
        results = self.db.query("user:", order_by='age')
        ages = [r['age'] for r in results]
        self.assertEqual(ages, sorted(ages))

    def test_query_order_by_desc(self):
        results = self.db.query("user:", order_by='-age')
        ages = [r['age'] for r in results]
        self.assertEqual(ages, sorted(ages, reverse=True))

    def test_query_limit(self):
        results = self.db.query("user:", order_by='-age', limit=3)
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0]['name'], 'Charlie')  # age 35

    def test_query_columns(self):
        results = self.db.query("user:", columns=['name', 'age'])
        for r in results:
            self.assertIn('_key', r)
            self.assertIn('name', r)
            self.assertIn('age', r)
            self.assertNotIn('city', r)

    def test_query_combined(self):
        results = self.db.query("user:",
            where=lambda v: v['age'] >= 30,
            columns=['name', 'age'],
            order_by='-age',
            limit=2)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]['name'], 'Charlie')
        self.assertEqual(results[1]['name'], 'Eve')

    def test_query_key_in_result(self):
        results = self.db.query("user:", where=lambda v: v['name'] == 'Alice')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['_key'], 'user:1')

    def test_query_no_match(self):
        results = self.db.query("user:", where=lambda v: v['city'] == 'Tokyo')
        self.assertEqual(results, [])

    def test_query_excludes_expired(self):
        self.db.put("user:6", {"name": "Frank", "age": 40, "city": "NYC"}, ttl=0.1)
        time.sleep(0.2)
        results = self.db.query("user:", where=lambda v: v['name'] == 'Frank')
        self.assertEqual(results, [])

    def test_query_non_dict_raises(self):
        self.db.put("user:bad", "not a dict")
        with self.assertRaises(TypeError):
            self.db.query("user:")

    def test_query_non_dict_skip_invalid(self):
        self.db.put("user:bad", "not a dict")
        results = self.db.query("user:", skip_invalid=True)
        keys = [r['_key'] for r in results]
        self.assertNotIn('user:bad', keys)
        self.assertEqual(len(results), 5)

    def test_query_in_transaction(self):
        with self.db.transaction():
            self.db.put("user:6", {"name": "Frank", "age": 22, "city": "NYC"})
            results = self.db.query("user:", where=lambda v: v['age'] < 25)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['name'], 'Frank')

    def test_query_empty_prefix(self):
        self.db.put("config:theme", {"value": "dark"})
        results = self.db.query("")
        self.assertGreater(len(results), 5)

    def test_query_wrong_prefix(self):
        results = self.db.query("order:")
        self.assertEqual(results, [])


class TestUpdateWhere(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = _db(self.tmp)
        self.db.put_many({
            "user:1": {"name": "Alice", "age": 30, "city": "NYC", "active": True},
            "user:2": {"name": "Bob",   "age": 25, "city": "SF",  "active": True},
            "user:3": {"name": "Charlie","age": 35, "city": "NYC", "active": True},
        })

    def tearDown(self):
        for f in os.listdir(self.tmp):
            os.remove(os.path.join(self.tmp, f))

    def test_update_where_matching(self):
        count = self.db.update_where("user:",
            where=lambda v: v['city'] == 'NYC',
            updates={'active': False})
        self.assertEqual(count, 2)
        results = self.db.query("user:", where=lambda v: v['active'] == False)
        self.assertEqual(len(results), 2)

    def test_update_where_all(self):
        count = self.db.update_where("user:", updates={'verified': True})
        self.assertEqual(count, 3)
        results = self.db.query("user:", where=lambda v: v.get('verified'))
        self.assertEqual(len(results), 3)

    def test_update_where_no_match(self):
        count = self.db.update_where("user:",
            where=lambda v: v['city'] == 'Tokyo',
            updates={'active': False})
        self.assertEqual(count, 0)

    def test_update_where_persists(self):
        self.db.update_where("user:",
            where=lambda v: v['name'] == 'Bob',
            updates={'age': 26})
        db2 = _db(self.tmp)
        result = db2.query("user:", where=lambda v: v['name'] == 'Bob')
        self.assertEqual(result[0]['age'], 26)

    def test_update_where_empty_updates_raises(self):
        with self.assertRaises(ValueError):
            self.db.update_where("user:", updates={})

    def test_update_where_non_dict_raises(self):
        self.db.put("user:bad", "not a dict")
        with self.assertRaises(TypeError):
            self.db.update_where("user:", updates={'active': False})

    def test_update_where_in_transaction(self):
        with self.db.transaction():
            self.db.update_where("user:",
                where=lambda v: v['city'] == 'NYC',
                updates={'active': False})
        results = self.db.query("user:", where=lambda v: v['active'] == False)
        self.assertEqual(len(results), 2)

    def test_update_where_rollback(self):
        try:
            with self.db.transaction():
                self.db.update_where("user:", updates={'active': False})
                raise ValueError("abort")
        except ValueError:
            pass
        results = self.db.query("user:", where=lambda v: v['active'] == True)
        self.assertEqual(len(results), 3)


class TestDeleteWhere(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = _db(self.tmp)
        self.db.put_many({
            "user:1": {"name": "Alice", "age": 30, "city": "NYC"},
            "user:2": {"name": "Bob",   "age": 25, "city": "SF"},
            "user:3": {"name": "Charlie","age": 35, "city": "NYC"},
        })

    def tearDown(self):
        for f in os.listdir(self.tmp):
            os.remove(os.path.join(self.tmp, f))

    def test_delete_where_matching(self):
        count = self.db.delete_where("user:",
            where=lambda v: v['city'] == 'NYC')
        self.assertEqual(count, 2)
        self.assertEqual(self.db.count(), 1)

    def test_delete_where_all(self):
        count = self.db.delete_where("user:")
        self.assertEqual(count, 3)
        self.assertEqual(self.db.count(), 0)

    def test_delete_where_no_match(self):
        count = self.db.delete_where("user:",
            where=lambda v: v['city'] == 'Tokyo')
        self.assertEqual(count, 0)
        self.assertEqual(self.db.count(), 3)

    def test_delete_where_persists(self):
        self.db.delete_where("user:", where=lambda v: v['name'] == 'Bob')
        db2 = _db(self.tmp)
        result = db2.query("user:", where=lambda v: v['name'] == 'Bob')
        self.assertEqual(result, [])

    def test_delete_where_non_dict_raises(self):
        self.db.put("user:bad", "not a dict")
        with self.assertRaises(TypeError):
            self.db.delete_where("user:")

    def test_delete_where_in_transaction(self):
        with self.db.transaction():
            self.db.delete_where("user:", where=lambda v: v['city'] == 'NYC')
        self.assertEqual(self.db.count(), 1)

    def test_delete_where_rollback(self):
        try:
            with self.db.transaction():
                self.db.delete_where("user:")
                raise ValueError("abort")
        except ValueError:
            pass
        self.assertEqual(self.db.count(), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)


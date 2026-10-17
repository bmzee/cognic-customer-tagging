"""The profile store: rebuild determinism, migrations, read-only access,
corrupt or partial store detection, retention and the runs table."""

import datetime
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

import engine
from engine import build, profile
from engine import store as store_module
from engine.store import StoreError
from tests.helpers import ROOT, TAXONOMY, CsvFiles, raw_taxonomy

DATA = os.path.join(ROOT, "data")
CUSTOMERS = os.path.join(DATA, "customers.csv")
TRANSACTIONS = os.path.join(DATA, "transactions.csv")


class StoreCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="tagging-store-")
        cls.path = os.path.join(cls.dir, "profile.db")
        cls.summary = build.rebuild(CUSTOMERS, TRANSACTIONS, cls.path, TAXONOMY)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def copy(self, name):
        target = os.path.join(self.dir, name)
        shutil.copy(self.path, target)
        return target


class Rebuild(StoreCase):
    def test_same_inputs_give_a_byte_identical_export(self):
        other = os.path.join(self.dir, "again.db")
        build.rebuild(CUSTOMERS, TRANSACTIONS, other, TAXONOMY)
        first, second = store_module.open_store(self.path, TAXONOMY), store_module.open_store(other, TAXONOMY)
        try:
            self.assertEqual(store_module.export(first), store_module.export(second))
        finally:
            first.close()
            second.close()

    def test_the_store_holds_what_a_batch_run_computes(self):
        run = engine.run(CUSTOMERS, TRANSACTIONS)
        connection = store_module.open_store(self.path, TAXONOMY)
        try:
            for cid in run.results:
                held = [row[0] for row in connection.execute(
                    "SELECT tag_id FROM tag_state WHERE customer_id = ? AND status = 'held'", (cid,))]
                self.assertEqual(sorted(held), sorted(run.tags_for(cid)), cid)
                for tag_id, entered in connection.execute(
                        "SELECT tag_id, entered_on FROM tag_state WHERE customer_id = ? AND status = 'held'", (cid,)):
                    expected = run.lifecycles[cid].entered_on[tag_id]
                    self.assertEqual(entered, expected.isoformat() if expected else None, (cid, tag_id))
            row = connection.execute(
                "SELECT reason, evidence FROM tag_state WHERE customer_id = 'C0001' AND tag_id = 'salary-earner'"
            ).fetchone()
            self.assertEqual(row[0], run.results["C0001"]["salary-earner"].reason)
            self.assertEqual(json.loads(row[1]), json.loads(json.dumps(run.results["C0001"]["salary-earner"].evidence)))
        finally:
            connection.close()

    def test_buckets_reproduce_the_engines_buckets(self):
        customers, _ = engine.load_customers(CUSTOMERS, TAXONOMY.base_currency)
        txns, as_of, _, _ = engine.load_transactions(TRANSACTIONS, customers, TAXONOMY)
        data = engine.customer_data(TAXONOMY, customers["C0011"], txns["C0011"])
        expected = {("{:04d}-{:02d}".format(*ym), key): agg.to_record() for (ym, key), agg in data.all_buckets().items()}
        connection = store_module.open_store(self.path, TAXONOMY)
        try:
            stored = {(month, key): {"n": n, "total": total, "max": mx, "credit": credit, "debit": debit,
                                     "last_day": last, "extra": extra}
                      for key, month, n, total, mx, credit, debit, last, extra in connection.execute(
                          "SELECT feature_key, month, n, total, max, credit, debit, last_day, extra "
                          "FROM feature_buckets WHERE customer_id = 'C0011'")}
        finally:
            connection.close()
        self.assertEqual(stored, {k: dict(v) for k, v in expected.items()})

    def test_runs_records_what_was_built_from_what(self):
        connection = store_module.open_store(self.path, TAXONOMY)
        try:
            row = connection.execute(
                "SELECT kind, as_of, taxonomy_version, taxonomy_hash, input_snapshot_hash, customers, transactions, "
                "tags_held, started_at, finished_at FROM runs").fetchone()
        finally:
            connection.close()
        self.assertEqual(row[:4], ("rebuild", "2026-09-30", TAXONOMY.version, TAXONOMY.content_hash))
        self.assertTrue(row[4].startswith("sha256:"))
        self.assertEqual(row[5], 300)
        self.assertEqual(row[7], self.summary["tags_held"])
        self.assertTrue(row[8] and row[9])

    def test_a_rebuild_records_tag_prevalence_for_drift(self):
        connection = store_module.open_store(self.path, TAXONOMY)
        try:
            run_id = connection.execute("SELECT run_id FROM runs").fetchone()[0]
            recorded = {tag: (held, suppressed, not_evaluated) for tag, held, suppressed, not_evaluated in
                        connection.execute("SELECT tag_id, held, suppressed, not_evaluated FROM run_tags "
                                           "WHERE run_id = ?", (run_id,))}
            live = {tag: [0, 0, 0] for tag in TAXONOMY.by_id}
            for tag, status, number in connection.execute(
                    "SELECT tag_id, status, COUNT(*) FROM tag_state GROUP BY tag_id, status"):
                live[tag][("held", "suppressed", "not_evaluated").index(status)] = number
            spread = dict(connection.execute("SELECT band, customers FROM run_spread WHERE run_id = ?", (run_id,)))
            holders = connection.execute(
                "SELECT COUNT(DISTINCT customer_id) FROM tag_state WHERE status = 'held'").fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(recorded, {tag: tuple(v) for tag, v in live.items()})
        self.assertEqual(sorted(spread), ["0", "1", "2", "3", "4+"])
        self.assertEqual(sum(spread.values()), 300)
        self.assertEqual(spread["0"], 300 - holders)
        self.assertEqual(sum(held for held, _, _ in recorded.values()), self.summary["tags_held"])

    def test_the_export_leaves_out_the_clock(self):
        connection = store_module.open_store(self.path, TAXONOMY)
        try:
            text = store_module.export(connection)
        finally:
            connection.close()
        runs = [json.loads(line) for line in text.splitlines() if '"table":"runs"' in line]
        self.assertEqual(len(runs), 1)
        self.assertNotIn("started_at", runs[0]["row"])
        self.assertNotIn("finished_at", runs[0]["row"])

    def test_meta_records_the_build(self):
        connection = store_module.open_store(self.path, TAXONOMY)
        try:
            meta = store_module.meta(connection)
        finally:
            connection.close()
        self.assertEqual(meta["state"], "ready")
        self.assertEqual(meta["taxonomy_hash"], TAXONOMY.content_hash)
        self.assertEqual(meta["history_months"], str(TAXONOMY.history_months))
        self.assertEqual(meta["lifecycle_months"], str(TAXONOMY.lifecycle_months))


class Retention(unittest.TestCase):
    def test_only_the_retained_months_are_kept(self):
        folder = tempfile.mkdtemp(prefix="tagging-ret-")
        try:
            path = os.path.join(folder, "p.db")
            as_of = datetime.date(2027, 6, 30)
            build.rebuild(CUSTOMERS, TRANSACTIONS, path, TAXONOMY, as_of)
            start = profile.retention_start(as_of, TAXONOMY).isoformat()
            self.assertEqual(start, "2025-11-01")  # 13 + 6 months before June 2027
            connection = store_module.open_store(path, TAXONOMY)
            try:
                oldest = connection.execute("SELECT MIN(posted_date) FROM ledger").fetchone()[0]
                oldest_bucket = connection.execute("SELECT MIN(month) FROM feature_buckets").fetchone()[0]
                self.assertGreaterEqual(oldest, start)
                self.assertGreaterEqual(oldest_bucket, start[:7])
                self.assertEqual(store_module.meta(connection)["retention_start"], start)
            finally:
                connection.close()
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class Migrations(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="tagging-mig-")
        self.path = os.path.join(self.dir, "m.db")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_migrations_apply_in_order_from_an_empty_store_and_only_once(self):
        connection = store_module.connect_rw(self.path)
        try:
            applied = store_module.apply_migrations(connection)
            self.assertEqual(applied, [v for v, _, _, _ in store_module.migrations()])
            self.assertEqual(store_module.apply_migrations(connection), [])
            tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            for table in ("meta", "customers", "ledger", "features", "feature_buckets", "tag_state",
                          "checkpoint_tags", "tag_history", "runs", "run_tags", "run_spread", "schema_migrations"):
                self.assertIn(table, tables)
        finally:
            connection.close()

    def test_a_changed_migration_is_refused(self):
        connection = store_module.connect_rw(self.path)
        try:
            store_module.apply_migrations(connection)
            connection.execute("UPDATE schema_migrations SET checksum = 'sha256:0' WHERE version = 1")
            with self.assertRaises(StoreError):
                store_module.apply_migrations(connection)
        finally:
            connection.close()

    def test_an_unknown_migration_is_refused(self):
        connection = store_module.connect_rw(self.path)
        try:
            store_module.apply_migrations(connection)
            connection.execute("INSERT INTO schema_migrations VALUES (99, 'future', 'sha256:1')")
            with self.assertRaises(StoreError):
                store_module.apply_migrations(connection)
        finally:
            connection.close()


class BadStores(StoreCase):
    def _refused(self, path, message, taxonomy=TAXONOMY):
        with self.assertRaises(StoreError) as ctx:
            store_module.open_store(path, taxonomy).close()
        self.assertIn(message, str(ctx.exception))

    def test_missing_file(self):
        self._refused(os.path.join(self.dir, "nope.db"), "no profile store")

    def test_garbage_file(self):
        path = os.path.join(self.dir, "garbage.db")
        with open(path, "wb") as handle:
            handle.write(b"this is not a database at all" * 100)
        self._refused(path, "not a readable SQLite store")

    def test_truncated_store(self):
        path = self.copy("truncated.db")
        with open(path, "r+b") as handle:
            handle.truncate(os.path.getsize(path) // 3)
        with self.assertRaises(StoreError):
            store_module.open_store(path, TAXONOMY).close()

    def test_half_built_store(self):
        path = self.copy("building.db")
        connection = sqlite3.connect(path)
        connection.execute("UPDATE meta SET value = 'building' WHERE key = 'state'")
        connection.commit()
        connection.close()
        self._refused(path, "incomplete")

    def test_store_from_another_taxonomy(self):
        raw = raw_taxonomy()
        next(t for t in raw["tags"] if t["id"] == "rent-payer")["rule"]["all"][0]["value"] = 4
        self._refused(self.path, "rebuild it", engine.load_taxonomy_data(raw))

    def test_store_with_a_tampered_migration(self):
        path = self.copy("tampered.db")
        connection = sqlite3.connect(path)
        connection.execute("UPDATE schema_migrations SET checksum = 'sha256:0'")
        connection.commit()
        connection.close()
        self._refused(path, "do not match")


class ReadOnly(StoreCase):
    def test_a_read_only_connection_cannot_write(self):
        connection = store_module.open_store(self.path, TAXONOMY)
        try:
            for statement in ("DELETE FROM tag_state", "INSERT INTO meta VALUES ('x', 'y')",
                              "CREATE TABLE sneaky (x)", "UPDATE meta SET value = 'x' WHERE key = 'state'"):
                with self.subTest(statement=statement):
                    with self.assertRaises(sqlite3.OperationalError):
                        connection.execute(statement)
        finally:
            connection.close()
        store_module.open_store(self.path, TAXONOMY).close()


class Atomic(unittest.TestCase):
    def test_a_failed_rebuild_leaves_the_previous_store_untouched(self):
        files = CsvFiles()
        try:
            files.customer("C1")
            files.txn("C1", "2026-09-01", "-50.00")
            customers, transactions = files.write()
            path = os.path.join(files.dir, "profile.db")
            build.rebuild(customers, transactions, path, TAXONOMY)
            before = open(path, "rb").read()
            with open(transactions, "w", encoding="utf-8") as handle:
                handle.write("customer_id,amount\nC1,5\n")  # no posted_date column
            with self.assertRaises(engine.DataError):
                build.rebuild(customers, transactions, path, TAXONOMY)
            self.assertEqual(open(path, "rb").read(), before)
            self.assertFalse(os.path.exists(path + ".building"))
        finally:
            files.cleanup()

    def test_the_store_is_never_written_over_an_input(self):
        with self.assertRaises(engine.DataError):
            build.rebuild(CUSTOMERS, TRANSACTIONS, TRANSACTIONS, TAXONOMY)


class CommandLine(unittest.TestCase):
    def test_rebuild_and_export(self):
        folder = tempfile.mkdtemp(prefix="tagging-cli-")
        env = dict(os.environ, PYTHONPATH=ROOT, PYTHONDONTWRITEBYTECODE="1")
        try:
            path = os.path.join(folder, "p.db")
            result = subprocess.run([sys.executable, "-m", "engine.build", "--rebuild", "--customers", CUSTOMERS,
                                     "--transactions", TRANSACTIONS, "--store", path], cwd=ROOT, env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("300 customers", result.stdout)
            result = subprocess.run([sys.executable, "-m", "engine.build", "--export", "--store", path], cwd=ROOT,
                                    env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(result.stdout.startswith('{"row":'))
            result = subprocess.run([sys.executable, "-m", "engine.build", "--export", "--store",
                                     os.path.join(folder, "missing.db")], cwd=ROOT, env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("no profile store", result.stderr)
        finally:
            shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

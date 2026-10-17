"""Customer rights: an objection to profiling is a hard exclusion. The
builder never stores an opted-out customer, forgets one at once when the
objection arrives (however late), drops their later events, and keeps only
the id and the date; the reader then has no profile for them."""

import csv
import datetime
import os
import shutil
import tempfile
import unittest

import engine
from engine import build, policy
from engine import events as ev
from engine import store as store_module
from engine.incremental import CUSTOMER_TABLES, Follower
from server.tools import Reader
from tests.helpers import ROOT, TAXONOMY

DATA = os.path.join(ROOT, "data")
WHO = "C0001"   # salaried every month in the synthetic data
LATENESS = 3


def copy_data(folder, opted_out=(), value="true"):
    """The synthetic data with a profiling_opt_out column, set for some customers."""
    with open(os.path.join(DATA, "customers.csv"), encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    rows[0].append("profiling_opt_out")
    for row in rows[1:]:
        row.append(value if row[0] in opted_out else "")
    path = os.path.join(folder, "customers.csv")
    with open(path, "w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, lineterminator="\n").writerows(rows)
    shutil.copy(os.path.join(DATA, "transactions.csv"), os.path.join(folder, "transactions.csv"))
    return path, os.path.join(folder, "transactions.csv")


def holdings(connection, cid):
    """{table: rows} for every table that still holds something about cid."""
    found = {}
    for table in CUSTOMER_TABLES:
        count = connection.execute("SELECT COUNT(*) FROM {} WHERE customer_id = ?".format(table), (cid,)).fetchone()[0]
        if count:
            found[table] = count
    return found


class Values(unittest.TestCase):
    def test_anything_but_an_empty_or_negative_value_opts_out(self):
        for value in ("true", "TRUE", "yes", "Y", "1", "objected", "maybe"):
            self.assertTrue(policy.opted_out(value), value)
        for value in ("", None, "false", "No", "n", "0", "  "):
            self.assertFalse(policy.opted_out(value), value)

    def test_the_column_is_read_and_is_not_a_protected_trait(self):
        self.assertIn("profiling_opt_out", policy.CUSTOMER_COLUMNS)
        self.assertIsNone(policy.protected_reason("profiling_opt_out"))

    def test_an_objection_needs_no_other_attribute(self):
        event = ev.parse(ev.make("o1", "customer.updated", "2026-09-01", WHO, {"profiling_opt_out": "true"}))
        self.assertTrue(ev.is_opt_out(event))
        with self.assertRaises(ev.EventError):
            ev.parse(ev.make("o2", "customer.updated", "2026-09-01", WHO, {"profiling_opt_out": "false"}))


class PrintOnlyEngine(unittest.TestCase):
    def test_an_opted_out_customer_is_not_tagged(self):
        folder = tempfile.mkdtemp(prefix="tagging-optout-")
        try:
            customers, transactions = copy_data(folder, {WHO})
            result = engine.run(customers, transactions, TAXONOMY)
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        self.assertNotIn(WHO, result.results)
        self.assertEqual(result.customer_notes["opted_out"], 1)
        self.assertGreater(result.run_notes["skipped"]["opted_out"], 0)
        self.assertNotIn("unknown_customer", result.run_notes["skipped"])
        self.assertIn("C0002", result.results)


class Rebuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="tagging-optout-")
        customers, transactions = copy_data(cls.dir, {WHO, "C0011"})
        cls.store = os.path.join(cls.dir, "profile.db")
        build.rebuild(customers, transactions, cls.store, TAXONOMY)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_nothing_but_the_id_and_date_is_stored(self):
        connection = store_module.open_store(self.store, TAXONOMY)
        try:
            for cid in (WHO, "C0011"):
                self.assertEqual(holdings(connection, cid), {}, cid)
            self.assertEqual(connection.execute("SELECT customer_id, since FROM opt_outs ORDER BY 1").fetchall(),
                             [("C0001", ev.EPOCH), ("C0011", ev.EPOCH)])
            notes = connection.execute("SELECT notes FROM runs").fetchone()[0]
            self.assertIn('"opted_out":2', notes)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM customers").fetchone()[0], 298)
        finally:
            connection.close()

    def test_the_reader_has_no_profile_and_lists_no_one_who_opted_out(self):
        reader = Reader(self.store, TAXONOMY)
        self.assertFalse(reader.call("get_customer_tags", {"customer_id": WHO})["found"])
        self.assertFalse(reader.call("customer_tag_history", {"customer_id": WHO})["found"])
        listed = reader.call("find_customers_by_tag", {"tag_id": "salary-earner", "page": 1, "page_size": 50})
        self.assertNotIn(WHO, [c["customer_id"] for c in listed["customers"]])
        self.assertEqual(reader.call("tag_summary", {})["customers"], 298)

    def test_every_profile_table_equals_a_store_built_without_the_customers(self):
        folder = tempfile.mkdtemp(prefix="tagging-optout-")
        try:
            gone = {WHO, "C0011"}
            for name in ("customers.csv", "transactions.csv"):
                with open(os.path.join(DATA, name), encoding="utf-8", newline="") as handle:
                    rows = list(csv.reader(handle))
                with open(os.path.join(folder, name), "w", encoding="utf-8", newline="") as handle:
                    csv.writer(handle, lineterminator="\n").writerows(
                        [rows[0]] + [r for r in rows[1:] if r[rows[0].index("customer_id")] not in gone])
            path = os.path.join(folder, "without.db")
            build.rebuild(os.path.join(folder, "customers.csv"), os.path.join(folder, "transactions.csv"), path,
                          TAXONOMY)
            without = store_module.open_store(path, TAXONOMY)
            opted = store_module.open_store(self.store, TAXONOMY)
            try:
                # Event ids follow line numbers, so compare the tables that describe customers.
                tables = ("customers", "customer_versions", "closures", "ledger", "feature_buckets", "tag_state",
                          "checkpoint_tags", "tag_history")
                self.assertEqual(store_module.export(opted, tables), store_module.export(without, tables))
            finally:
                without.close()
                opted.close()
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class Following(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="tagging-optout-follow-")
        self.store = os.path.join(self.dir, "profile.db")
        build.rebuild(os.path.join(DATA, "customers.csv"), os.path.join(DATA, "transactions.csv"), self.store,
                      TAXONOMY)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_an_objection_forgets_the_customer_at_once_and_later_events_are_dropped(self):
        follower = Follower(self.store, TAXONOMY, LATENESS, clock=lambda: "t")
        try:
            self.assertNotEqual(holdings(follower.connection, WHO), {})
            counts = follower.apply([ev.make("objection", "customer.updated", "2026-10-01", WHO,
                                             {"profiling_opt_out": "yes"}, version=9)])
            self.assertEqual(counts["opted_out"], 1)
            self.assertEqual(holdings(follower.connection, WHO), {})
            later = follower.apply([
                ev.make("after-1", "transaction.posted", "2026-10-02", WHO,
                        {"txn_id": "z1", "amount": "-12.00", "currency": "USD", "category": "groceries"}),
                ev.make("after-2", "customer.updated", "2026-10-02", WHO, {"home_currency": "USD"}, version=10),
                ev.make("tick", "clock.tick", "2026-10-02")])
            self.assertEqual((later["opted_out"], later["applied"]), (2, 1))
            self.assertEqual(holdings(follower.connection, WHO), {})
            self.assertEqual(follower.connection.execute(
                "SELECT since FROM opt_outs WHERE customer_id = ?", (WHO,)).fetchone()[0], "2026-10-01")
        finally:
            follower.close()
        self.assertFalse(Reader(self.store, TAXONOMY).call("get_customer_tags", {"customer_id": WHO})["found"])

    def test_a_late_objection_is_still_honoured_and_the_earliest_date_kept(self):
        follower = Follower(self.store, TAXONOMY, LATENESS, clock=lambda: "t")
        try:
            follower.apply([ev.make("objection-1", "customer.updated", "2026-09-29", WHO,
                                    {"profiling_opt_out": "true"}, version=9)])
            old = datetime.date(2026, 6, 1)   # far beyond the allowed lateness
            counts = follower.apply([ev.make("objection-0", "customer.updated", old, WHO,
                                             {"profiling_opt_out": "true"}, version=8)])
            self.assertEqual((counts["opted_out"], counts["late"]), (1, 0))
            self.assertEqual(follower.connection.execute(
                "SELECT since FROM opt_outs WHERE customer_id = ?", (WHO,)).fetchone()[0], "2026-06-01")
            self.assertEqual(holdings(follower.connection, WHO), {})
        finally:
            follower.close()


if __name__ == "__main__":
    unittest.main()

"""The seeded generator reproduces the committed data and only writes synthetic values."""

import csv
import os
import re
import shutil
import sys
import tempfile
import unittest

from tests.helpers import ROOT

DATA = os.path.join(ROOT, "data")
sys.path.insert(0, DATA)
import generate  # noqa: E402


class Reproducible(unittest.TestCase):
    def test_same_seed_gives_byte_identical_files(self):
        out = tempfile.mkdtemp(prefix="tagging-gen-")
        try:
            generate.write(generate.build(generate.SEED), out)
            for name in ("customers.csv", "transactions.csv", "expected_tags.json"):
                with open(os.path.join(out, name), "rb") as a, open(os.path.join(DATA, name), "rb") as b:
                    self.assertEqual(a.read(), b.read(), name)
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_a_different_seed_changes_the_background(self):
        a = generate.build(1)
        b = generate.build(2)
        self.assertNotEqual([len(p.rows) for p in a.people], [len(p.rows) for p in b.people])


class SyntheticOnly(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(DATA, "customers.csv"), encoding="utf-8", newline="") as handle:
            cls.customers = list(csv.DictReader(handle))
        with open(os.path.join(DATA, "transactions.csv"), encoding="utf-8", newline="") as handle:
            cls.txns = list(csv.DictReader(handle))

    def test_size(self):
        self.assertEqual(len(self.customers), 300)
        self.assertTrue(4500 <= len(self.txns) <= 5500, len(self.txns))

    def test_twelve_months(self):
        dates = sorted(t["posted_date"] for t in self.txns if t["posted_date"])
        self.assertGreaterEqual(dates[0], "2025-10-01")
        self.assertLessEqual(dates[-1], "2026-09-30")

    def test_customer_columns_hold_no_protected_traits(self):
        self.assertEqual(list(self.customers[0]), generate.CUSTOMER_COLUMNS)

    def test_identifiers_are_obviously_synthetic(self):
        for row in self.customers:
            self.assertRegex(row["display_name"], r"^Synthetic Customer \d{4}$")
            self.assertRegex(row["account_id"], r"^SYN-ACC-\d{6}$")
        pattern = re.compile(r"^(SYN-[A-Z]+-\d+)?$")
        for row in self.txns:
            self.assertRegex(row["account_id"], r"^SYN-ACC-\d{6}$")
            self.assertTrue(pattern.match(row["counterparty"]), row["counterparty"])


if __name__ == "__main__":
    unittest.main()

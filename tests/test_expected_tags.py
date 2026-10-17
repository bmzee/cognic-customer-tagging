"""The engine's tags for the labelled synthetic customers match data/expected_tags.json."""

import json
import os
import unittest

import engine
from tests.helpers import ROOT, TAXONOMY

DATA = os.path.join(ROOT, "data")


class ExpectedTags(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(DATA, "expected_tags.json"), encoding="utf-8") as handle:
            cls.expected = json.load(handle)
        cls.result = engine.run(os.path.join(DATA, "customers.csv"), os.path.join(DATA, "transactions.csv"))

    def test_as_of_matches(self):
        self.assertEqual(self.result.as_of.isoformat(), self.expected["as_of"])

    def test_labelled_customers_get_exactly_their_expected_tags(self):
        for entry in self.expected["customers"]:
            cid = entry["customer_id"]
            with self.subTest(customer=cid, scenario=entry["scenario"]):
                self.assertEqual(sorted(self.result.tags_for(cid)), entry["expected_tags"])
                if "expected_not_evaluated" in entry:
                    unknown = sorted(t for t, r in self.result.results[cid].items() if r.state is None)
                    self.assertEqual(unknown, entry["expected_not_evaluated"])

    def test_labelled_subset_covers_every_tag(self):
        covered = set()
        for entry in self.expected["customers"]:
            covered.update(entry["expected_tags"])
        self.assertEqual(covered, set(TAXONOMY.by_id))

    def test_labelled_subset_includes_near_misses(self):
        self.assertGreaterEqual(sum("near miss" in e["scenario"] for e in self.expected["customers"]), 10)

    def test_every_labelled_customer_states_what_cannot_be_evaluated(self):
        for entry in self.expected["customers"]:
            self.assertIn("expected_not_evaluated", entry, entry["customer_id"])

    def test_malformed_rows_are_reported(self):
        self.assertEqual(self.result.run_notes["skipped"], {
            "bad_or_missing_date": 1, "sign_conflict": 1, "unknown_currency": 1, "zero_amount": 1})


if __name__ == "__main__":
    unittest.main()

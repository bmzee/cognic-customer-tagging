"""The drift report: thresholds, baselines, the spread index, and the
committed example report regenerated from a followed synthetic store."""

import os
import shutil
import sys
import tempfile
import unittest

from tests.helpers import ROOT

sys.path.insert(0, os.path.join(ROOT, "tools"))
import drift  # noqa: E402

TAGS = ("salary-earner", "saver", "dormant")


def run(run_id, customers, held, content_hash="sha256:a", spread=None):
    """A run as read_runs returns it: held maps tag to customers holding it."""
    return {"store": "s.db", "order": 0, "run_id": run_id, "kind": "follow", "as_of": "2026-{:02d}-28".format(run_id),
            "taxonomy_version": "2.0.0", "taxonomy_hash": content_hash, "customers": customers,
            "tags": {tag: {"held": held.get(tag, 0), "suppressed": 0, "not_evaluated": 0} for tag in TAGS},
            "spread": spread or {"0": customers // 2, "1": customers // 4, "2": customers // 8,
                                 "3": customers // 16, "4+": customers - customers // 2 - customers // 4
                                 - customers // 8 - customers // 16}}


def levels(result, index):
    return {t["tag"]: t["level"] for t in result["runs"][index]["tags"]}


BASE = {"salary-earner": 3000, "saver": 1000, "dormant": 500}


class Thresholds(unittest.TestCase):
    def test_alert_warn_and_ok_against_a_frozen_baseline(self):
        runs = [run(i, 10000, BASE) for i in (1, 2, 3)]
        runs.append(run(4, 10000, dict(BASE, **{"salary-earner": 1400})))   # -53%, -16 points
        runs.append(run(5, 10000, dict(BASE, **{"salary-earner": 2100})))   # -30%, -9 points
        runs.append(run(6, 10000, dict(BASE, **{"salary-earner": 2950})))   # -1.7%
        result = drift.analyse(runs)
        self.assertEqual([r["role"] for r in result["runs"]], ["baseline"] * 3 + ["compared"] * 3)
        self.assertEqual(levels(result, 3)["salary-earner"], "alert")
        self.assertEqual(levels(result, 4)["salary-earner"], "warn")
        self.assertEqual(levels(result, 5)["salary-earner"], "ok")
        self.assertEqual(result["runs"][3]["level"], "alert")
        self.assertEqual({levels(result, 3)[t] for t in ("saver", "dormant")}, {"ok"})

    def test_a_large_relative_change_of_few_points_is_not_flagged(self):
        small = dict(BASE, saver=50)
        runs = [run(i, 10000, small) for i in (1, 2, 3)] + [run(4, 10000, dict(small, saver=90))]  # +80%, 0.4 points
        self.assertEqual(levels(drift.analyse(runs), 3)["saver"], "ok")

    def test_a_change_that_chance_explains_is_not_flagged(self):
        runs = [run(i, 200, {"saver": 20}) for i in (1, 2, 3)] + [run(4, 200, {"saver": 28})]  # +40%, 4 points
        self.assertEqual(levels(drift.analyse(runs), 3)["saver"], "ok")

    def test_falling_to_zero_alerts_only_when_holders_were_expected(self):
        runs = [run(i, 10000, dict(BASE, saver=3)) for i in (1, 2, 3)]
        runs.append(run(4, 10000, dict(BASE, dormant=0, saver=0)))
        result = drift.analyse(runs)
        self.assertEqual(levels(result, 3)["dormant"], "alert")
        self.assertEqual(levels(result, 3)["saver"], "ok")

    def test_a_population_change_of_a_fifth_alerts(self):
        runs = [run(i, 10000, BASE) for i in (1, 2, 3)] + [run(4, 7900, {k: int(v * 0.79) for k, v in BASE.items()})]
        result = drift.analyse(runs)
        self.assertEqual(result["runs"][3]["population_level"], "alert")
        self.assertEqual(set(levels(result, 3).values()), {"ok"})


class Baselines(unittest.TestCase):
    def test_a_taxonomy_change_starts_a_new_baseline(self):
        runs = [run(i, 10000, BASE) for i in (1, 2, 3, 4)]
        runs += [run(i, 10000, dict(BASE, **{"salary-earner": 1000}), "sha256:b") for i in (5, 6, 7, 8)]
        result = drift.analyse(runs)
        self.assertEqual([r["role"] for r in result["runs"]],
                         ["baseline"] * 3 + ["compared"] + ["baseline"] * 3 + ["compared"])
        self.assertEqual(levels(result, 7)["salary-earner"], "ok")

    def test_nothing_is_flagged_while_the_baseline_is_forming(self):
        runs = [run(1, 10000, BASE), run(2, 10000, dict(BASE, **{"salary-earner": 10}))]
        result = drift.analyse(runs)
        self.assertTrue(all(r["baseline_forming"] for r in result["runs"]))
        self.assertEqual({r["level"] for r in result["runs"]}, {"ok"})


class Spread(unittest.TestCase):
    def test_the_stability_index(self):
        same = {"0": 500, "1": 250, "2": 125, "3": 60, "4+": 65}
        self.assertAlmostEqual(drift.psi(same, same), 0.0)
        shifted = {"0": 100, "1": 150, "2": 250, "3": 250, "4+": 250}
        self.assertGreater(drift.psi(same, shifted), drift.PSI_ALERT)
        with_empty = dict(same, **{"4+": 0})
        self.assertTrue(drift.psi(same, with_empty) > 0)
        held = {"salary-earner": 300, "saver": 100}
        runs = [run(i, 1000, held, spread=same) for i in (1, 2, 3)] + [run(4, 1000, held, spread=shifted)]
        result = drift.analyse(runs)
        self.assertEqual(result["runs"][3]["psi_level"], "alert")
        self.assertLess(result["runs"][3]["psi_critical"], drift.PSI_WARN)


class ExampleReport(unittest.TestCase):
    def test_the_committed_report_is_current(self):
        with open(os.path.join(ROOT, "docs", "drift-report.md"), encoding="utf-8") as handle:
            committed = handle.read()
        self.assertEqual(committed, drift.demo_report(),
                         "docs/drift-report.md is stale: python3 tools/drift.py demo --out docs/drift-report.md")

    def test_the_report_reads_stores_without_changing_them(self):
        folder = tempfile.mkdtemp(prefix="tagging-drift-test-")
        try:
            path = drift.build_demo_store(os.path.join(folder, "s.db"))
            with open(path, "rb") as handle:
                before = handle.read()
            runs = drift.read_runs([path, path])
            with open(path, "rb") as handle:
                after = handle.read()
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        self.assertEqual(before, after)
        self.assertEqual(len(runs), 14)
        self.assertEqual([r["as_of"] for r in runs[:2]], ["2026-03-31", "2026-03-31"])

    def test_drift_reads_counts_only(self):
        with open(os.path.join(ROOT, "engine", "migrations", "0003_run_prevalence.sql"), encoding="utf-8") as handle:
            sql = handle.read()
        self.assertNotIn("customer_id", sql)


if __name__ == "__main__":
    unittest.main()

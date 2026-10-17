"""The fairness kit: its statistics, its verdicts, a small end-to-end run of
the null, planted-proxy and canary scenarios, and the wall between the kit's
synthetic attributes and the engine and reader."""

import os
import re
import shutil
import sys
import tempfile
import unittest

from tests.helpers import ROOT

sys.path.insert(0, os.path.join(ROOT, "tools"))
import fairness  # noqa: E402


def row(rates, members=1000, polarity="neutral"):
    """Measure one tag on one attribute from rates by group, then judge it alone."""
    groups, holders = [], set()
    for g, rate in sorted(rates.items()):
        start = len(groups)
        groups.extend([g] * members)
        holders.update(range(start, start + int(round(rate * members))))
    result = fairness.disparity(holders, groups, {g: members for g in rates}, polarity)
    return fairness.judge(result, 1)


class Statistics(unittest.TestCase):
    def test_fishers_exact_test(self):
        # Three of four against one of four: two-sided p = 34/70.
        self.assertAlmostEqual(fairness.fisher_exact(3, 4, 1, 4), 34 / 70.0, places=6)
        self.assertAlmostEqual(fairness.fisher_exact(2, 4, 2, 4), 1.0, places=6)

    def test_chi_square_tail(self):
        self.assertAlmostEqual(fairness.gamma_q(0.5, 3.841459 / 2), 0.05, places=5)
        self.assertAlmostEqual(fairness.gamma_q(1.0, 2.0), 0.1353352832, places=8)   # df 2: exp(-x/2)
        self.assertAlmostEqual(fairness.gamma_q(2.0, 13.2767 / 2), 0.01, places=4)   # df 4, the drift value

    def test_association(self):
        self.assertAlmostEqual(fairness.cramers_v([[50, 0], [0, 50]])[0], 1.0)
        self.assertAlmostEqual(fairness.cramers_v([[25, 25], [25, 25]])[0], 0.0)
        self.assertAlmostEqual(fairness.uncertainty([[50, 0], [0, 50]]), 1.0)
        self.assertAlmostEqual(fairness.uncertainty([[25, 25], [25, 25]]), 0.0)

    def test_two_proportions_switches_to_fisher_for_small_cells(self):
        self.assertEqual(fairness.two_proportions(2, 40, 1, 40)[1], "fisher")
        p, kind = fairness.two_proportions(400, 1000, 500, 1000)
        self.assertEqual(kind, "z")
        self.assertLess(p, 0.0001)


class Verdicts(unittest.TestCase):
    def test_a_large_significant_gap_fails(self):
        r = row({"g1": 0.40, "g2": 0.20}, members=2000)
        self.assertEqual((r["tier"], r["verdict"]), ("adequate", "FAIL"))
        self.assertAlmostEqual(r["ratio"], 0.5)

    def test_a_small_gap_passes_and_a_moderate_association_warns(self):
        self.assertEqual(row({"g1": 0.40, "g2": 0.38}, members=2000)["verdict"], "PASS")
        warned = row({"g1": 0.80, "g2": 0.66}, members=2000)       # ratio 0.825, V about 0.16
        self.assertEqual(warned["verdict"], "WARN")
        self.assertGreater(warned["ratio"], 0.8)
        self.assertEqual(row({"g1": 0.60, "g2": 0.46}, members=2000)["verdict"], "FAIL")

    def test_too_few_tagged_is_inconclusive_and_too_few_members_insufficient(self):
        self.assertEqual(row({"g1": 0.10, "g2": 0.05}, members=1000)["verdict"], "inconclusive")
        self.assertEqual(row({"g1": 0.5, "g2": 0.1}, members=20)["verdict"], "insufficient")
        self.assertEqual(row({"g1": 0.001, "g2": 0.002}, members=1000)["verdict"], "insufficient")

    def test_the_reference_and_harmed_group_follow_polarity(self):
        benefit = row({"g1": 0.40, "g2": 0.20}, 2000, "benefit")
        burden = row({"g1": 0.40, "g2": 0.20}, 2000, "burden")
        neutral = row({"g1": 0.40, "g2": 0.20}, 2000, "neutral")
        self.assertEqual((benefit["reference"], benefit["harmed"]), ("g1", "g2"))
        self.assertEqual((burden["reference"], burden["harmed"]), ("g2", "g1"))
        self.assertEqual((neutral["harmed"], neutral["verdict"]), (None, "FAIL"))   # every polarity is gated

    def test_the_correction_counts_every_comparison(self):
        groups = ["g1"] * 1000 + ["g2"] * 1000
        r = fairness.disparity(set(range(400)) | set(range(1000, 1315)), groups, {"g1": 1000, "g2": 1000},
                               "neutral")                                    # 40% against 31.5%: ratio 0.79
        self.assertEqual(fairness.judge(dict(r), 1)["verdict"], "FAIL")
        self.assertEqual(fairness.judge(dict(r), 10000)["verdict"], "WARN")   # not significant after correction


class SmallRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = fairness.run(chunks=1, replicas=10, background=1000, permutations=5)

    def test_the_gate_passes(self):
        failed = [check for check, ok in self.result["gate"].items() if not ok]
        self.assertEqual(failed, [])
        self.assertTrue(self.result["passed"])

    def test_the_canaries_are_caught_and_the_near_miss_is_not(self):
        rows = self.result["results"]["canary"]["rows"]
        self.assertEqual(rows[("canary-strong", "trait_b")]["verdict"], "FAIL")
        self.assertEqual(rows[("canary-subtle", "trait_b")]["verdict"], "FAIL")
        self.assertNotEqual(rows[("canary-near-miss", "trait_b")]["verdict"], "FAIL")
        self.assertLess(rows[("canary-strong", "trait_b")]["ratio"], 0.3)

    def test_no_real_tag_fails_on_independent_or_proxy_attributes(self):
        for variant in ("null", "planted-proxy"):
            rows = self.result["results"][variant]["rows"]
            self.assertEqual(sorted(k for k, r in rows.items() if r["verdict"] == "FAIL"), [], variant)
            self.assertEqual(len(rows), 54 * 3)

    def test_the_report_states_the_result_and_the_synthetic_basis(self):
        text = fairness.markdown(self.result)
        self.assertIn("## Result: PASS", text)
        self.assertIn("Everything here is synthetic", text)
        self.assertIn(self.result["taxonomy_hash"], text)


class PlantedProxies(unittest.TestCase):
    def test_the_plants_change_the_data_the_engine_reads(self):
        null, attributes = fairness.population(fairness.SEED, 0, 2, 200, "null")
        planted, _ = fairness.population(fairness.SEED, 0, 2, 200, "planted-proxy")
        restricted = {r[0] for r in fairness.RESTRICTED}
        before = [(p.cid, r["category"], r["country"]) for p in null.people for r in p.rows]
        after = [(p.cid, r["category"], r["country"]) for p in planted.people for r in p.rows]
        self.assertEqual(len(before), len(after))
        self.assertNotEqual(before, after)
        for person in planted.people:
            group = attributes[person.cid]["trait_a"]
            for r in person.rows:
                if r["category"] in restricted:
                    self.assertEqual(r["category"], fairness.PLANTED_RESTRICTED[group][0])

    def test_the_identity_check_sees_a_real_change(self):
        folder = tempfile.mkdtemp(prefix="tagging-fairness-test-")
        try:
            digests = {}
            for variant in ("null", "canary"):
                combined, attributes = fairness.population(fairness.SEED, 0, 2, 200, variant)
                path = os.path.join(folder, variant)
                os.makedirs(path)
                fairness.write_chunk(path, combined, attributes, variant)
                digests[variant] = fairness.evaluate(path, fairness.real_taxonomy())[2]
                with open(os.path.join(path, "customers.csv"), encoding="utf-8") as handle:
                    header = handle.readline()
                self.assertNotIn("trait_", header)
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        self.assertNotEqual(digests["null"], digests["canary"])


class TheWall(unittest.TestCase):
    def test_the_engine_and_reader_never_see_the_attributes_or_the_kit(self):
        pattern = re.compile(r"attributes\.csv|trait_[abc]|import fairness|tools\.fairness|fairness\.py|canary")
        for folder in ("engine", "server", "bin"):
            for base, _, files in os.walk(os.path.join(ROOT, folder)):
                for name in files:
                    if name.endswith(".pyc"):
                        continue
                    with open(os.path.join(base, name), encoding="utf-8", errors="replace") as handle:
                        match = pattern.search(handle.read())
                    self.assertIsNone(match, os.path.join(base, name))

    def test_the_kit_writes_attributes_beside_the_inputs_never_into_them(self):
        folder = tempfile.mkdtemp(prefix="tagging-fairness-test-")
        try:
            combined, attributes = fairness.population(fairness.SEED, 0, 1, 50, "null")
            fairness.write_chunk(folder, combined, attributes, "null")
            self.assertEqual(sorted(os.listdir(folder)),
                             ["attributes.csv", "customers.csv", "expected_tags.json", "transactions.csv"])
            self.assertEqual(fairness.read_attributes(folder), attributes)
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class CommittedReport(unittest.TestCase):
    def test_the_report_matches_this_taxonomy_engine_and_kit(self):
        import engine
        with open(os.path.join(ROOT, "docs", "fairness-report.md"), encoding="utf-8") as handle:
            text = handle.read()
        taxonomy = fairness.real_taxonomy()
        self.assertIn("(kit {}) for taxonomy {} (`{}`), engine {}.".format(
            fairness.KIT_VERSION, taxonomy.version, taxonomy.content_hash, engine.ENGINE_VERSION), text,
            "docs/fairness-report.md is stale: rerun the fairness workflow and commit its report")
        self.assertIn("## Result: PASS", text)


if __name__ == "__main__":
    unittest.main()

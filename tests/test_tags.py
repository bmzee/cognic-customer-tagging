"""Every tag fires on its positive case and not on its near miss."""

import unittest

from tests import tag_cases
from tests.helpers import TAXONOMY


class EveryTagHasCases(unittest.TestCase):
    def test_every_taxonomy_tag_has_a_positive_and_a_near_miss(self):
        self.assertEqual(sorted(tag_cases.CASES), sorted(t["id"] for t in TAXONOMY.tags))


class PositiveAndNearMiss(unittest.TestCase):
    def _check(self, tag_id, positive, near_miss):
        with self.subTest(tag=tag_id, case="positive"):
            results = positive().evaluate()
            self.assertIs(results[tag_id].state, True,
                          "{} should fire: {}".format(tag_id, results[tag_id].evidence))
        with self.subTest(tag=tag_id, case="near miss"):
            results = near_miss().evaluate()
            self.assertIs(results[tag_id].state, False,
                          "{} should not fire: {}".format(tag_id, results[tag_id].evidence))

    def test_all_tags(self):
        for tag_id, (positive, near_miss) in tag_cases.CASES.items():
            self._check(tag_id, positive, near_miss)

    def test_saver_surplus_branch(self):
        self._check("saver", *tag_cases.SAVER_SURPLUS)

    def test_reason_is_filled_and_rule_is_shown(self):
        for tag_id, (positive, _) in tag_cases.CASES.items():
            result = positive().evaluate()[tag_id]
            with self.subTest(tag=tag_id):
                self.assertNotIn("{", result.reason)
                self.assertTrue(result.rule)
                self.assertTrue(result.evidence)
                for item in result.evidence:
                    self.assertIn(item["result"], ("met", "not met", "unknown"))
                    self.assertIn("threshold_display", item)


def _make_test(tag_id):
    def test(self):
        positive, near_miss = tag_cases.CASES[tag_id]
        self._check(tag_id, positive, near_miss)
    return test


for _tag_id in tag_cases.CASES:
    setattr(PositiveAndNearMiss, "test_tag_" + _tag_id.replace("-", "_"), _make_test(_tag_id))


if __name__ == "__main__":
    unittest.main()

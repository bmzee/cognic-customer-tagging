"""The taxonomy file: shape, fairness guard, strict validation, data-driven rules."""

import copy
import json
import re
import unittest

import engine
from engine import policy
from engine.taxonomy import TaxonomyError, iter_leaves, load_taxonomy_data
from engine.evaluate import evaluate_customer
from tests.helpers import AS_OF, TAXONOMY, Case


def raw_copy():
    with open(engine.DEFAULT_TAXONOMY, encoding="utf-8") as handle:
        return json.load(handle)


def tag_of(raw, tag_id):
    return next(t for t in raw["tags"] if t["id"] == tag_id)


class Shape(unittest.TestCase):
    def test_between_25_and_40_tags_with_unique_ids(self):
        ids = [t["id"] for t in TAXONOMY.tags]
        self.assertTrue(25 <= len(ids) <= 40, len(ids))
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_tag_has_the_required_parts(self):
        for tag in TAXONOMY.tags:
            with self.subTest(tag=tag["id"]):
                for key in ("id", "name", "description", "fields", "rule", "reason"):
                    self.assertTrue(tag[key], key)
                leaves = list(iter_leaves(tag["rule"]))
                self.assertTrue(all("op" in leaf and "value" in leaf for leaf in leaves))
                has_window = any("window" in leaf or leaf["metric"] in ("ratio", "tenure_days") for leaf in leaves)
                self.assertTrue(has_window, "every tag needs a time window or a tenure threshold")

    def test_declared_fields_equal_the_fields_the_rule_reads(self):
        for tag in TAXONOMY.tags:
            self.assertEqual(sorted(tag["fields"]), TAXONOMY.derived_fields[tag["id"]], tag["id"])

    def test_reason_windows_match_the_rule_windows(self):
        """A reason saying 'last 6 months' must come from a 6-month window in that tag."""
        for tag in TAXONOMY.tags:
            windows = set()
            for leaf in list(iter_leaves(tag["rule"])) + tag.get("facts", []):
                specs = [leaf.get("window")]
                if leaf["metric"] == "ratio":
                    specs += [leaf["numerator"]["window"], leaf["denominator"]["window"]]
                for spec in filter(None, specs):
                    unit = "days" if "days" in spec else "months"
                    windows.add((spec[unit], unit, spec.get("offset_" + unit, 0) > 0))
            with self.subTest(tag=tag["id"]):
                for n, unit in re.findall(r"last (\d+) (days|months)", tag["reason"]):
                    self.assertIn((int(n), unit, False), windows, tag["reason"])
                for n, unit in re.findall(r"(\d+) (days|months) before", tag["reason"]):
                    self.assertIn((int(n), unit, True), windows, tag["reason"])


class Fairness(unittest.TestCase):
    def test_fairness_block_documents_exclusions(self):
        fairness = TAXONOMY.raw["fairness"]
        for trait in ("religion", "ethnicity", "gender", "disability", "marital status"):
            self.assertIn(trait, fairness["excluded_traits"])
        self.assertIn("bank policy decides", fairness["age"])

    def test_no_tag_text_mentions_a_protected_trait_or_age(self):
        for tag in TAXONOMY.tags:
            text = " ".join([tag["id"], tag["name"], tag["description"], tag["reason"]] + tag["fields"] +
                            [leaf["description"] for leaf in iter_leaves(tag["rule"])])
            with self.subTest(tag=tag["id"]):
                for word in re.findall(r"[a-z]+", text.lower()):
                    self.assertNotIn(word, policy.PROTECTED_TOKENS | policy.AGE_TOKENS)

    def _refused(self, mutate, message):
        raw = raw_copy()
        mutate(raw)
        with self.assertRaises(TaxonomyError) as ctx:
            load_taxonomy_data(raw)
        self.assertIn(message, str(ctx.exception))

    def test_protected_trait_filter_is_refused(self):
        def mutate(raw):
            tag_of(raw, "salary-earner")["rule"]["all"][0]["filter"]["gender"] = "x"
        self._refused(mutate, "protected trait")

    def test_age_field_is_refused_with_the_policy_note(self):
        def mutate(raw):
            tag_of(raw, "salary-earner")["rule"]["all"][0]["filter"]["age_band"] = "x"
        self._refused(mutate, "bank policy decides")

    def test_proxy_category_cannot_select_transactions(self):
        for category in ("healthcare", "charity", "school_fees", "pension", "religious_donation"):
            with self.subTest(category=category):
                def mutate(raw, category=category):
                    tag_of(raw, "bill-payer")["rule"]["all"][0]["filter"]["category"] = [category]
                self._refused(mutate, "category")

    def test_proxy_category_may_be_excluded(self):
        raw = raw_copy()
        tag_of(raw, "salary-earner")["rule"]["all"][0]["filter"]["category"] = {"not_in": ["healthcare"]}
        load_taxonomy_data(raw)

    def test_protected_distinct_field_is_refused(self):
        def mutate(raw):
            tag_of(raw, "subscription-user")["rule"]["all"][0]["field"] = "ethnicity"
        self._refused(mutate, "protected trait")


class StrictValidation(unittest.TestCase):
    def _refused(self, mutate, message):
        raw = raw_copy()
        mutate(raw)
        with self.assertRaises(TaxonomyError) as ctx:
            load_taxonomy_data(raw)
        self.assertIn(message, str(ctx.exception))

    def test_unknown_key(self):
        self._refused(lambda raw: tag_of(raw, "rent-payer").update(score=5), "unknown key")

    def test_unknown_metric(self):
        self._refused(lambda raw: tag_of(raw, "rent-payer")["rule"]["all"][0].update(metric="magic"), "unknown metric")

    def test_unknown_op(self):
        self._refused(lambda raw: tag_of(raw, "rent-payer")["rule"]["all"][0].update(op="~"), "unknown op")

    def test_threshold_must_be_a_number(self):
        self._refused(lambda raw: tag_of(raw, "rent-payer")["rule"]["all"][0].update(value="5"), "expected a number")

    def test_bad_window(self):
        self._refused(lambda raw: tag_of(raw, "rent-payer")["rule"]["all"][0].update(window={"weeks": 2}), "window")

    def test_declared_fields_must_match(self):
        self._refused(lambda raw: tag_of(raw, "rent-payer")["fields"].pop(), "declared fields")

    def test_reason_placeholder_must_exist(self):
        self._refused(lambda raw: tag_of(raw, "rent-payer").update(reason="paid {nothing}"), "names no condition")

    def test_dependency_cycle_is_refused(self):
        def mutate(raw):
            dormant = tag_of(raw, "dormant")
            dormant["rule"]["all"].append({"id": "loop", "description": "x", "metric": "tag",
                                           "tag": "going-dormant", "op": "==", "value": False})
        self._refused(mutate, "cycle")

    def test_unknown_dependency_is_refused(self):
        def mutate(raw):
            tag_of(raw, "going-dormant")["rule"]["all"][1]["tag"] = "no-such-tag"
        self._refused(mutate, "unknown tag")

    def test_duplicate_json_keys_are_refused(self):
        import os
        import tempfile
        with open(engine.DEFAULT_TAXONOMY, encoding="utf-8") as source:
            text = source.read()
        text = text.replace('"schema_version": "1",', '"schema_version": "1", "schema_version": "1",', 1)
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        try:
            handle.write(text)
            handle.close()
            with self.assertRaises(TaxonomyError):
                engine.load_taxonomy(handle.name)
        finally:
            os.unlink(handle.name)


class RulesComeFromTheFile(unittest.TestCase):
    def test_changing_a_threshold_in_the_json_changes_the_result(self):
        case = Case().salary(3000)
        self.assertIn("salary-earner", case.tags())
        raw = raw_copy()
        tag_of(raw, "salary-earner")["rule"]["all"][0]["value"] = 7
        stricter = load_taxonomy_data(raw)
        results = evaluate_customer(stricter, case.customer, case.txns, AS_OF)
        self.assertIs(results["salary-earner"].state, False)

    def test_removing_a_tag_from_the_json_removes_it(self):
        raw = raw_copy()
        raw["tags"] = [t for t in raw["tags"] if t["id"] != "rent-payer"]
        self.assertNotIn("rent-payer", load_taxonomy_data(raw).by_id)

    def test_rates_are_read_from_the_settings(self):
        raw = raw_copy()
        raw["settings"]["fx_rates_to_base"]["EUR"] = "2"
        self.assertEqual(str(load_taxonomy_data(raw).fx_rates["EUR"]), "2")


if __name__ == "__main__":
    unittest.main()

"""The taxonomy file: shape, fairness guard, strict validation, version and
hash, data-driven rules."""

import copy
import os
import re
import tempfile
import unittest

import engine
from engine import policy
from engine.evaluate import evaluate_customer
from engine.taxonomy import TaxonomyError, compute_content_hash, iter_leaves, load_taxonomy_data, read_json
from tests.helpers import AS_OF, TAXONOMY, Case, raw_taxonomy

TAXONOMY_DIR = os.path.dirname(engine.DEFAULT_TAXONOMY)
PLAN_GROUPS = {"income", "spending-pattern", "channel-and-digital", "travel", "savings-and-balances", "card-use",
               "bills-and-subscriptions", "engagement-and-lifecycle", "financial-stress"}


def tag_of(raw, tag_id):
    return next(t for t in raw["tags"] if t["id"] == tag_id)


def reference_tables():
    return (read_json(os.path.join(TAXONOMY_DIR, "counterparties.json")),
            read_json(os.path.join(TAXONOMY_DIR, "merchant_codes.json")))


class Shape(unittest.TestCase):
    def test_between_45_and_60_tags_with_unique_ids(self):
        ids = [t["id"] for t in TAXONOMY.tags]
        self.assertTrue(45 <= len(ids) <= 60, len(ids))
        self.assertEqual(len(ids), len(set(ids)))

    def test_groups_cover_the_plan_and_each_has_tags(self):
        self.assertTrue(PLAN_GROUPS <= set(TAXONOMY.groups), sorted(PLAN_GROUPS - set(TAXONOMY.groups)))
        for group in TAXONOMY.groups:
            with self.subTest(group=group):
                self.assertGreaterEqual(sum(t["group"] == group for t in TAXONOMY.tags), 2)

    def test_lifecycle_stages_are_one_exclusive_group(self):
        groups = {g["id"]: g["priority"] for g in TAXONOMY.exclusive_groups}
        self.assertEqual(groups["lifecycle"], ["dormant", "going-dormant", "re-engaged", "new-customer",
                                               "active-customer"])

    def test_every_tag_has_the_required_parts(self):
        for tag in TAXONOMY.tags:
            with self.subTest(tag=tag["id"]):
                for key in ("id", "name", "description", "fields", "rule", "reason", "limitations"):
                    self.assertTrue(tag[key], key)
                self.assertIn(tag["polarity"], ("benefit", "burden", "neutral"))
                leaves = list(iter_leaves(tag["rule"]))
                self.assertTrue(all("op" in leaf and "value" in leaf for leaf in leaves))
                has_window = any("window" in leaf or leaf["metric"] in ("ratio", "tenure_days") for leaf in leaves)
                self.assertTrue(has_window, "every tag needs a time window or a tenure threshold")

    def test_financial_stress_tags_are_burden_and_support_only(self):
        for tag in TAXONOMY.tags:
            if tag["group"] == "financial-stress":
                with self.subTest(tag=tag["id"]):
                    self.assertEqual(tag["polarity"], "burden")
                    self.assertTrue(any("never for credit" in text for text in tag["limitations"]))

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
                for n, unit in re.findall(r"last (\d+) (?:complete )?(days|months)", tag["reason"]):
                    self.assertIn((int(n), unit, False), windows, tag["reason"])
                for n, unit in re.findall(r"(\d+) (days|months) before", tag["reason"]):
                    self.assertIn((int(n), unit, True), windows, tag["reason"])

    def test_governance_states_the_intended_and_prohibited_uses(self):
        governance = TAXONOMY.governance
        self.assertIn("relationship manager", governance["intended_use"])
        text = " ".join(governance["prohibited_uses"])
        for use in ("credit", "pricing", "fraud", "AML", "automated decision"):
            self.assertIn(use, text)


class VersionAndHash(unittest.TestCase):
    def test_stored_hash_matches_the_content_and_the_changelog(self):
        raw = read_json(engine.DEFAULT_TAXONOMY)
        self.assertRegex(raw["taxonomy_version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(raw["content_hash"], TAXONOMY.content_hash)
        last = raw["changelog"][-1]
        self.assertEqual((last["version"], last["content_hash"]), (raw["taxonomy_version"], raw["content_hash"]))

    def test_a_rule_change_changes_the_hash(self):
        raw = raw_taxonomy()
        tables = reference_tables()
        before = compute_content_hash(raw, *tables)
        tag_of(raw, "salary-earner")["rule"]["all"][0]["value"] = 5
        self.assertNotEqual(compute_content_hash(raw, *tables), before)

    def test_a_reference_table_change_changes_the_hash(self):
        raw = raw_taxonomy()
        counterparties, codes = reference_tables()
        before = compute_content_hash(raw, counterparties, codes)
        codes = copy.deepcopy(codes)
        codes["codes"]["5411"]["category"] = "shopping"
        self.assertNotEqual(compute_content_hash(raw, counterparties, codes), before)

    def test_key_order_does_not_change_the_hash(self):
        raw = raw_taxonomy()
        tables = reference_tables()
        reordered = dict(reversed(list(raw.items())))
        self.assertEqual(compute_content_hash(reordered, *tables), compute_content_hash(raw, *tables))

    def test_a_changed_rule_with_the_old_hash_is_refused(self):
        raw = read_json(engine.DEFAULT_TAXONOMY)
        tag_of(raw, "rent-payer")["rule"]["all"][0]["value"] = 4
        with self.assertRaises(TaxonomyError) as ctx:
            load_taxonomy_data(raw)
        self.assertIn("content_hash does not match", str(ctx.exception))

    def test_a_new_hash_needs_a_changelog_entry(self):
        raw = read_json(engine.DEFAULT_TAXONOMY)
        tag_of(raw, "rent-payer")["rule"]["all"][0]["value"] = 4
        raw["content_hash"] = compute_content_hash(
            {k: v for k, v in raw.items() if k not in ("content_hash", "changelog")}, *reference_tables())
        with self.assertRaises(TaxonomyError) as ctx:
            load_taxonomy_data(raw)
        self.assertIn("changelog", str(ctx.exception))

    def test_outputs_record_the_version_and_hash(self):
        run = engine.run(os.path.join(os.path.dirname(TAXONOMY_DIR), "data", "customers.csv"),
                         os.path.join(os.path.dirname(TAXONOMY_DIR), "data", "transactions.csv"), lifecycle=False)
        from engine import output
        record = output.run_record(run, ["C0001"])
        self.assertEqual(record["taxonomy_version"], TAXONOMY.version)
        self.assertEqual(record["taxonomy_hash"], TAXONOMY.content_hash)


class Fairness(unittest.TestCase):
    def test_fairness_block_documents_exclusions(self):
        fairness = TAXONOMY.raw["fairness"]
        for trait in ("religion", "ethnicity", "national origin", "gender", "sexual orientation", "disability",
                      "health", "pregnancy", "family or marital status", "political opinion"):
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
        raw = raw_taxonomy()
        mutate(raw)
        with self.assertRaises(TaxonomyError) as ctx:
            load_taxonomy_data(raw)
        self.assertIn(message, str(ctx.exception))

    def test_protected_trait_filter_is_refused(self):
        for field in ("gender", "national_origin", "sexual_orientation", "health_status", "political_party",
                      "trade_union", "family_size"):
            with self.subTest(field=field):
                def mutate(raw, field=field):
                    tag_of(raw, "salary-earner")["rule"]["all"][0]["filter"][field] = "x"
                self._refused(mutate, "protected trait")

    def test_age_field_is_refused_with_the_policy_note(self):
        for field in ("age_band", "date_of_birth", "retirement_date"):
            with self.subTest(field=field):
                def mutate(raw, field=field):
                    tag_of(raw, "salary-earner")["rule"]["all"][0]["filter"][field] = "x"
                self._refused(mutate, "bank policy decides")

    def test_proxy_category_cannot_select_transactions(self):
        for category in ("healthcare", "charity", "worship", "school_fees", "childcare", "pension",
                         "religious_donation", "restricted"):
            with self.subTest(category=category):
                def mutate(raw, category=category):
                    tag_of(raw, "bill-payer")["rule"]["all"][0]["filter"]["category"] = [category]
                self._refused(mutate, "category")

    def test_proxy_category_may_be_excluded(self):
        raw = raw_taxonomy()
        tag_of(raw, "salary-earner")["rule"]["all"][0]["filter"]["category"] = {"not_in": ["healthcare"]}
        load_taxonomy_data(raw)

    def test_a_specific_country_or_currency_cannot_be_selected(self):
        """Remittance and travel tags may ask "abroad or not", never which country or corridor."""
        for field, value in (("txn_country", ["AE"]), ("currency", ["GBP"]), ("counterparty_country", ["XX"])):
            with self.subTest(field=field):
                def mutate(raw, field=field, value=value):
                    tag_of(raw, "remittance-receiver")["rule"]["all"][0]["filter"][field] = value
                self._refused(mutate, "national origin" if field != "counterparty_country" else "corridor")

    def test_remittance_and_travel_tags_never_read_a_specific_country(self):
        for tag in TAXONOMY.tags:
            for leaf in iter_leaves(tag["rule"]):
                for flt in (leaf.get("filter", {}), leaf.get("of", {})):
                    self.assertFalse({"txn_country", "currency"} & set(flt), tag["id"])

    def test_protected_distinct_field_is_refused(self):
        def mutate(raw):
            tag_of(raw, "subscription-user")["rule"]["all"][0]["field"] = "ethnicity"
        self._refused(mutate, "protected trait")

    def test_a_tag_named_after_a_protected_trait_is_refused(self):
        def mutate(raw):
            tag_of(raw, "rent-payer")["name"] = "Pregnancy spending"
        self._refused(mutate, "protected trait")

    def test_unknown_counterparty_kind_is_refused(self):
        def mutate(raw):
            tag_of(raw, "regular-other-income")["rule"]["all"][0]["filter"]["counterparty_kind"] = ["church"]
        self._refused(mutate, "unknown counterparty kind")

    def test_governance_must_cover_every_prohibited_use(self):
        def mutate(raw):
            raw["governance"]["prohibited_uses"] = [u for u in raw["governance"]["prohibited_uses"]
                                                    if "pricing" not in u] + ["x"]
        self._refused(mutate, "pricing")


class StrictValidation(unittest.TestCase):
    def _refused(self, mutate, message):
        raw = raw_taxonomy()
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

    def test_polarity_must_be_known(self):
        self._refused(lambda raw: tag_of(raw, "rent-payer").update(polarity="good"), "polarity")

    def test_limitations_are_required(self):
        self._refused(lambda raw: tag_of(raw, "rent-payer").update(limitations=[]), "limitations")

    def test_unknown_group_is_refused(self):
        self._refused(lambda raw: tag_of(raw, "rent-payer").update(group="misc"), "unknown group")

    def test_exclusive_group_names_known_tags_once(self):
        self._refused(lambda raw: raw["exclusive_groups"][0]["priority"].append("no-such-tag"), "unknown tag")
        self._refused(lambda raw: raw["exclusive_groups"].append(
            {"id": "again", "description": "x", "priority": ["dormant", "saver"]}), "more than one exclusive group")

    def test_recurring_parameters_are_checked(self):
        def leaf(raw):
            return tag_of(raw, "many-subscriptions")["rule"]["all"][0]
        self._refused(lambda raw: leaf(raw).update(amount_tolerance=1.5), "fraction")
        self._refused(lambda raw: leaf(raw).update(period_months=0), "period_months")
        self._refused(lambda raw: leaf(raw).update(min_occurrences=12), "cannot fit")
        self._refused(lambda raw: leaf(raw).update(window={"days": 90}), "month window")

    def test_history_must_cover_the_longest_window(self):
        self._refused(lambda raw: raw["settings"].update(history_months=6), "history_months")

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
        with open(engine.DEFAULT_TAXONOMY, encoding="utf-8") as source:
            text = source.read()
        text = text.replace('"schema_version": "2",', '"schema_version": "2", "schema_version": "2",', 1)
        folder = tempfile.mkdtemp(prefix="tagging-tax-")
        try:
            path = os.path.join(folder, "tags.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
            for name in ("counterparties.json", "merchant_codes.json"):
                with open(os.path.join(TAXONOMY_DIR, name), encoding="utf-8") as src, \
                        open(os.path.join(folder, name), "w", encoding="utf-8") as dst:
                    dst.write(src.read())
            with self.assertRaises(TaxonomyError):
                engine.load_taxonomy(path)
        finally:
            import shutil
            shutil.rmtree(folder, ignore_errors=True)


class RulesComeFromTheFile(unittest.TestCase):
    def test_changing_a_threshold_in_the_json_changes_the_result(self):
        case = Case().salary(3000)
        self.assertIn("salary-earner", case.tags())
        raw = raw_taxonomy()
        tag_of(raw, "salary-earner")["rule"]["all"][0]["value"] = 7
        stricter = load_taxonomy_data(raw)
        results = evaluate_customer(stricter, case.customer, case.txns, AS_OF)
        self.assertIs(results["salary-earner"].state, False)

    def test_removing_a_tag_from_the_json_removes_it(self):
        raw = raw_taxonomy()
        raw["tags"] = [t for t in raw["tags"] if t["id"] != "rent-payer"]
        self.assertNotIn("rent-payer", load_taxonomy_data(raw).by_id)

    def test_rates_are_read_from_the_settings(self):
        raw = raw_taxonomy()
        raw["settings"]["fx_rates_to_base"]["EUR"] = "2"
        self.assertEqual(str(load_taxonomy_data(raw).fx_rates["EUR"]), "2")


if __name__ == "__main__":
    unittest.main()

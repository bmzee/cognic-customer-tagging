"""Reference tables and what happens to a transaction when it is read:
counterparty normalisation, merchant codes, restricted categories and
pseudonymised people."""

import copy
import datetime
import random
import unittest

from engine import data as data_module
from engine import reference
from engine.reference import Counterparties, MerchantCodes, ReferenceTableError, clean_counterparty
from tests.helpers import TAXONOMY, Case


def read(**fields):
    row = {"txn_id": "R1", "posted_date": "2026-09-10", "amount": "-20.00", "direction": "", "currency": "USD",
           "channel": "card_pos", "category": "", "counterparty": "", "txn_country": "US", "mcc": "",
           "balance_after": ""}
    row.update(fields)
    customer = data_module.Customer("C1", datetime.date(2024, 1, 1), "US", "USD")
    return data_module.normalise_transaction(row, customer, TAXONOMY)


class CounterpartyNormalisation(unittest.TestCase):
    def test_cleaning(self):
        self.assertEqual(clean_counterparty("  syn  streamco*0412 "), "SYN STREAMCO")
        self.assertEqual(clean_counterparty("SYNSTREAMCO.EXAMPLE 2201"), "SYNSTREAMCO.EXAMPLE")
        self.assertEqual(clean_counterparty("SYN-MERCHANT-0001 #77"), "SYN-MERCHANT-0001")
        self.assertEqual(clean_counterparty(""), "")

    def test_one_merchant_behind_different_descriptors(self):
        table = TAXONOMY.counterparties
        for raw in ("SYN STREAMCO*0412", "SYNSTREAMCO.EXAMPLE 2201", "SYN-STREAMCO", "syn streamco"):
            self.assertEqual(table.normalise(raw), ("SYN-STREAMCO", "merchant"), raw)
        self.assertEqual(table.normalise("SYN MUSICBOX 7781"), ("SYN-MUSICBOX", "merchant"))

    def test_kinds_and_unknowns(self):
        table = TAXONOMY.counterparties
        self.assertEqual(table.normalise("SYN-EMPLOYER-001"), ("SYN-EMPLOYER-001", "employer"))
        self.assertEqual(table.normalise("SYN-UTILITY-01"), ("SYN-UTILITY-01", "biller"))
        self.assertEqual(table.normalise("SOMETHING ELSE 123"), ("SOMETHING ELSE", "unknown"))
        self.assertEqual(table.normalise(""), (None, "unknown"))

    def test_rule_order_in_the_file_does_not_matter(self):
        raw = copy.deepcopy(TAXONOMY.counterparties.raw)
        shuffled = copy.deepcopy(raw)
        random.Random(7).shuffle(shuffled["rules"])
        a, b = Counterparties(raw), Counterparties(shuffled)
        for name in ("SYN STREAMCO*1", "SYN-PERSON-001", "SYN-CLIENT-9", "PAYROLL SYN-EMPLOYER-004", "X"):
            self.assertEqual(a.normalise(name), b.normalise(name), name)

    def test_malformed_tables_are_refused(self):
        raw = copy.deepcopy(TAXONOMY.counterparties.raw)
        raw["rules"].append({"match": "prefix", "pattern": "lower case", "counterparty": None, "kind": "merchant"})
        with self.assertRaises(ReferenceTableError):
            Counterparties(raw)
        raw = copy.deepcopy(TAXONOMY.counterparties.raw)
        raw["rules"].append({"match": "prefix", "pattern": "SYN-X", "counterparty": None, "kind": "church"})
        with self.assertRaises(ReferenceTableError):
            Counterparties(raw)


class People(unittest.TestCase):
    def test_a_person_is_kept_only_as_a_pseudonym(self):
        txn, _, _ = read(counterparty="SYN-PERSON-001", channel="mobile_app", category="transfer_out")
        self.assertEqual(txn.counterparty_kind, "person")
        self.assertRegex(txn.counterparty, r"^person-[0-9a-f]{12}$")
        self.assertNotIn("PERSON", txn.counterparty)
        again, _, _ = read(counterparty="syn-person-001 ", channel="mobile_app", category="transfer_out")
        self.assertEqual(again.counterparty, txn.counterparty)

    def test_a_business_keeps_its_name(self):
        txn, _, _ = read(counterparty="SYN-CLIENT-005", amount="500.00", category="business_income")
        self.assertEqual((txn.counterparty, txn.counterparty_kind), ("SYN-CLIENT-005", "business"))


class MerchantCodesAndCategories(unittest.TestCase):
    def test_the_code_fills_in_a_missing_category(self):
        txn, _, _ = read(mcc="4511")
        self.assertEqual((txn.category, txn.category_source), ("travel", "mcc"))

    def test_the_banks_own_category_wins(self):
        txn, _, _ = read(mcc="4511", category="shopping")
        self.assertEqual((txn.category, txn.category_source), ("shopping", "category"))

    def test_unknown_code_and_no_category(self):
        txn, _, _ = read(mcc="0000")
        self.assertEqual((txn.category, txn.category_source), ("uncategorized", "none"))

    def test_restricted_categories_are_collapsed_when_read(self):
        for fields in ({"category": "healthcare"}, {"category": "religious_donation"}, {"category": "school_fees"},
                       {"mcc": "8661"}, {"mcc": "8011"}, {"mcc": "8351"}, {"category": "pension", "amount": "500"}):
            with self.subTest(**fields):
                txn, _, _ = read(**fields)
                self.assertEqual(txn.category, "restricted")

    def test_the_profile_never_holds_a_restricted_category(self):
        case = Case()
        for day in range(1, 29):
            case.add(datetime.date(2026, 9, day), 50, "debit", "card_pos", "healthcare", "SYN-MERCHANT-0050")
        self.assertEqual({t.category for t in case.txns}, {"restricted"})

    def test_malformed_code_table_is_refused(self):
        raw = copy.deepcopy(TAXONOMY.merchant_codes.raw)
        raw["codes"]["12"] = {"category": "groceries", "label": "x"}
        with self.assertRaises(ReferenceTableError):
            MerchantCodes(raw)
        raw = copy.deepcopy(TAXONOMY.merchant_codes.raw)
        raw["codes"]["9999"] = {"category": "gender_clinic", "label": "x"}
        with self.assertRaises(ReferenceTableError):
            MerchantCodes(raw)


class Balances(unittest.TestCase):
    def test_balance_is_read_in_cents(self):
        txn, _, _ = read(balance_after="1234.56")
        self.assertEqual(txn.balance_cents, 123456)

    def test_a_bad_balance_skips_the_row(self):
        txn, reason, _ = read(balance_after="lots")
        self.assertIsNone(txn)
        self.assertEqual(reason, "bad_balance")

    def test_no_balance_data_means_not_evaluated(self):
        results = Case().salary(3000).evaluate()
        self.assertIsNone(results["repeated-low-balance"].state)
        self.assertEqual(results["repeated-low-balance"].missing, ["transactions.balance_after"])


class ReferenceModule(unittest.TestCase):
    def test_load_json_reads_a_table(self):
        import os
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "taxonomy",
                            "merchant_codes.json")
        self.assertIn("codes", reference.load_json(path))


if __name__ == "__main__":
    unittest.main()

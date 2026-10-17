"""Edge cases through real CSV files: no transactions, new customers,
missing fields, currency and sign handling, protected columns."""

import datetime
import unittest

import engine
from tests.helpers import AS_OF, LAST6, MONTHS, CsvFiles, on


class CsvTestCase(unittest.TestCase):
    def setUp(self):
        self.files = CsvFiles()

    def tearDown(self):
        self.files.cleanup()

    def run_engine(self, as_of=AS_OF, **write_args):
        customers, transactions = self.files.write(**write_args)
        return engine.run(customers, transactions, as_of=as_of)


class NoTransactions(CsvTestCase):
    def test_customer_without_transactions_gets_only_tenure_tags(self):
        self.files.customer("C1", open_date="2024-01-15")
        self.files.customer("C2")
        self.files.salary_months("C2")
        run = self.run_engine()
        self.assertEqual(run.tags_for("C1"), ["dormant"])
        self.assertEqual(run.per_customer_notes["C1"]["transactions_used"], 0)

    def test_empty_transactions_file_needs_an_explicit_as_of(self):
        self.files.customer("C1")
        with self.assertRaises(engine.DataError):
            self.run_engine(as_of=None)
        self.assertEqual(self.run_engine(as_of=AS_OF).tags_for("C1"), ["dormant"])


class NewCustomer(CsvTestCase):
    def test_new_customer_with_no_transactions(self):
        self.files.customer("C1", open_date=(AS_OF - datetime.timedelta(days=10)).isoformat())
        self.assertEqual(self.run_engine().tags_for("C1"), ["new-customer"])

    def test_new_customer_is_not_dormant_or_falling(self):
        self.files.customer("C1", open_date=(AS_OF - datetime.timedelta(days=40)).isoformat())
        self.files.txn("C1", "2026-09-05", "-120.00", "debit")
        self.files.txn("C1", "2026-09-25", "2500.00", "credit", channel="incoming", category="salary")
        self.assertEqual(self.run_engine().tags_for("C1"), ["new-customer"])

    def test_account_opened_after_as_of_is_not_new(self):
        self.files.customer("C1", open_date="2026-10-05")
        run = self.run_engine()
        result = run.results["C1"]["new-customer"]
        self.assertIs(result.state, False)
        self.assertIn("after the as-of date", result.evidence[0]["note"])


class MissingFields(CsvTestCase):
    def test_missing_open_date_means_not_evaluated_not_guessed(self):
        self.files.customer("C1", open_date="")
        self.files.salary_months("C1")
        run = self.run_engine()
        self.assertIn("salary-earner", run.tags_for("C1"))
        self.assertNotIn("new-customer", run.tags_for("C1"))
        result = run.results["C1"]["new-customer"]
        self.assertIsNone(result.state)
        self.assertEqual(result.missing, ["customers.account_open_date"])

    def test_missing_home_country_blocks_abroad_rules_only(self):
        self.files.customer("C1", home_country="")
        for ym, country in ((MONTHS[1], "GB"), (MONTHS[5], "FR"), (MONTHS[9], "GB")):
            self.files.txn("C1", on(ym, 16).isoformat(), "-80", "debit", "GBP", txn_country=country)
        run = self.run_engine()
        self.assertIsNone(run.results["C1"]["frequent-traveller"].state)
        self.assertEqual(run.results["C1"]["frequent-traveller"].missing, ["customers.home_country"])

    def test_bad_open_date_is_reported(self):
        self.files.customer("C1", open_date="15/01/2024")
        run = self.run_engine()
        self.assertEqual(run.customer_notes["problems"], {"bad_account_open_date": 1})
        self.assertIsNone(run.results["C1"]["new-customer"].state)

    def test_only_required_transaction_columns(self):
        self.files.customer("C1")
        for ym in MONTHS:
            self.files.txn("C1", on(ym, 10).isoformat(), "-50.00")
        run = self.run_engine(txn_columns=["customer_id", "posted_date", "amount"])
        self.assertEqual(run.per_customer_notes["C1"]["transactions_used"], 12)
        self.assertEqual(run.run_notes["skipped"], {})

    def test_missing_required_column_is_an_error(self):
        self.files.customer("C1")
        self.files.txn("C1", "2026-09-01", "-50.00")
        with self.assertRaises(engine.DataError) as ctx:
            self.run_engine(txn_columns=["customer_id", "amount"])
        self.assertIn("posted_date", str(ctx.exception))

    def test_rows_missing_date_or_amount_are_skipped_and_counted(self):
        self.files.customer("C1")
        self.files.txn("C1", "", "-50.00")
        self.files.txn("C1", "2026-09-01", "")
        self.files.txn("C1", "2026-13-01", "-50.00")
        self.files.txn("C1", "2026-09-02", "abc")
        self.files.txn("C1", "2026-09-03", "NaN")
        run = self.run_engine()
        self.assertEqual(run.per_customer_notes["C1"]["skipped"],
                         {"bad_or_missing_amount": 3, "bad_or_missing_date": 2})

    def test_empty_category_and_channel_get_defaults(self):
        self.files.customer("C1")
        self.files.txn("C1", "2026-09-01", "-50.00", channel="", category="")
        customers, transactions = self.files.write()
        cs, _ = engine.load_customers(customers, "USD")
        by_customer, _, _, _ = engine.load_transactions(transactions, cs, {"USD": 1})
        txn = by_customer["C1"][0]
        self.assertEqual((txn.channel, txn.category), ("unknown", "uncategorized"))


class Currency(CsvTestCase):
    def test_foreign_amounts_are_converted_before_thresholds(self):
        # 4,600 EUR is 5,060 USD at the fixed rate: above the 5,000 threshold.
        self.files.customer("EUR", home_currency="USD")
        self.files.salary_months("EUR", amount="4600.00", currency="EUR")
        self.files.customer("USD")
        self.files.salary_months("USD", amount="4600.00")
        run = self.run_engine()
        self.assertIn("high-inflow", run.tags_for("EUR"))
        self.assertNotIn("high-inflow", run.tags_for("USD"))
        facts = run.results["EUR"]["salary-earner"].facts
        self.assertEqual(facts[0]["display"], "5,060.00 USD")

    def test_unknown_currency_is_skipped_never_guessed(self):
        self.files.customer("C1")
        self.files.txn("C1", "2026-09-01", "-50.00", currency="ZZZ")
        run = self.run_engine()
        self.assertEqual(run.per_customer_notes["C1"]["skipped"], {"unknown_currency": 1})
        self.assertEqual(run.run_notes["skipped"], {"unknown_currency": 1})

    def test_empty_currency_means_the_customers_home_currency(self):
        self.files.customer("C1", home_currency="EUR")
        self.files.salary_months("C1", amount="4600.00", currency="")
        run = self.run_engine()
        self.assertIn("high-inflow", run.tags_for("C1"))
        self.assertEqual(run.per_customer_notes["C1"]["currency_defaulted"], 12)

    def test_lower_case_currency_is_accepted(self):
        self.files.customer("C1")
        self.files.salary_months("C1", amount="4600.00", currency="eur")
        self.assertIn("high-inflow", self.run_engine().tags_for("C1"))

    def test_foreign_currency_flag_uses_the_home_currency(self):
        # For a customer whose home currency is EUR, euro card spending is not foreign.
        self.files.customer("C1", home_currency="EUR")
        for day in (5, 10, 15):
            self.files.txn("C1", "2026-09-{:02d}".format(day), "-100.00", "debit", "EUR", channel="card_online")
        self.assertNotIn("foreign-currency-spender", self.run_engine().tags_for("C1"))


class Signs(CsvTestCase):
    def _bills(self, cid, amount, direction):
        for ym in LAST6:
            self.files.txn(cid, on(ym, 10).isoformat(), amount, direction, channel="internet_banking",
                           category="utilities")

    def test_signed_and_unsigned_conventions_give_the_same_tags(self):
        for cid, amount, direction in (("SIGNED", "-80.00", ""), ("UNSIGNED", "80.00", "debit"),
                                       ("BOTH", "-80.00", "debit"), ("ALIAS", "80.00", "DR")):
            self.files.customer(cid)
            self._bills(cid, amount, direction)
        run = self.run_engine()
        for cid in ("SIGNED", "UNSIGNED", "BOTH", "ALIAS"):
            self.assertEqual(run.tags_for(cid), ["bill-payer"], cid)

    def test_positive_amount_without_direction_is_a_credit(self):
        self.files.customer("C1")
        self.files.salary_months("C1", direction="")
        self.assertIn("salary-earner", self.run_engine().tags_for("C1"))

    def test_negative_credit_is_a_sign_conflict(self):
        self.files.customer("C1")
        self.files.salary_months("C1", amount="-3000.00", direction="credit")
        run = self.run_engine()
        self.assertNotIn("salary-earner", run.tags_for("C1"))
        self.assertEqual(run.per_customer_notes["C1"]["skipped"], {"sign_conflict": 12})

    def test_unknown_direction_and_zero_amount_are_skipped(self):
        self.files.customer("C1")
        self.files.txn("C1", "2026-09-01", "50.00", "sideways")
        self.files.txn("C1", "2026-09-02", "0.00", "debit")
        self.files.txn("C1", "2026-09-03", "-0.001", "debit")
        run = self.run_engine()
        self.assertEqual(run.per_customer_notes["C1"]["skipped"], {"bad_direction": 1, "zero_amount": 2})


class RowsOutsideTheData(CsvTestCase):
    def test_transactions_after_as_of_are_ignored_and_counted(self):
        self.files.customer("C1")
        self.files.salary_months("C1")
        self.files.txn("C1", "2026-10-03", "-50.00")
        run = self.run_engine()
        self.assertEqual(run.per_customer_notes["C1"]["skipped"], {"after_as_of": 1})

    def test_default_as_of_is_the_latest_transaction_date(self):
        self.files.customer("C1")
        self.files.salary_months("C1")
        run = self.run_engine(as_of=None)
        self.assertEqual(run.as_of, datetime.date(2026, 9, 25))

    def test_unknown_customer_and_duplicate_ids(self):
        self.files.customer("C1")
        self.files.txn("NOPE", "2026-09-01", "-50.00")
        self.files.txn("C1", "2026-09-01", "-50.00", txn_id="DUP")
        self.files.txn("C1", "2026-09-02", "-60.00", txn_id="DUP")
        run = self.run_engine()
        self.assertEqual(run.run_notes["skipped"], {"duplicate_txn_id": 1, "unknown_customer": 1})
        self.assertEqual(run.per_customer_notes["C1"]["transactions_used"], 1)

    def test_mid_month_as_of_uses_complete_months_only(self):
        self.files.customer("C1")
        self.files.salary_months("C1")
        run = self.run_engine(as_of=datetime.date(2026, 10, 17))
        evidence = run.results["C1"]["salary-earner"].evidence[0]
        self.assertEqual(evidence["window"], "2026-04-01 to 2026-09-30")
        self.assertIn("salary-earner", run.tags_for("C1"))


class ProtectedColumns(CsvTestCase):
    def test_protected_columns_are_never_loaded_and_change_nothing(self):
        self.files.customer("C1")
        self.files.salary_months("C1")
        plain = self.run_engine()
        plain_tags = plain.tags_for("C1")
        self.files.customers = []
        self.files.customer("C1", gender="SECRET-G", religion="SECRET-R", marital_status="SECRET-M",
                            date_of_birth="1990-01-01", ethnicity="SECRET-E", disability="SECRET-D")
        run = self.run_engine()
        self.assertEqual(run.tags_for("C1"), plain_tags)
        self.assertEqual(run.customer_notes["ignored_columns"],
                         ["date_of_birth", "disability", "display_name", "ethnicity", "gender",
                          "marital_status", "religion"])
        from engine import output
        text = output.to_json(output.run_record(run)) + output.to_csv(run) + output.explain_text(run, "C1")
        for secret in ("SECRET-G", "SECRET-R", "SECRET-M", "1990-01-01", "SECRET-E", "SECRET-D"):
            self.assertNotIn(secret, text)


if __name__ == "__main__":
    unittest.main()

"""Shared test helpers: build one customer's transactions in memory or as CSV files."""

import csv
import datetime
import os
import shutil
import tempfile

import engine
from engine import data as data_module
from engine import evaluate
from engine import lifecycle as lifecycle_module
from engine import taxonomy as taxonomy_module

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAXONOMY = engine.load_taxonomy(engine.DEFAULT_TAXONOMY)
AS_OF = datetime.date(2026, 9, 30)
MONTHS = [(2025, 10), (2025, 11), (2025, 12)] + [(2026, m) for m in range(1, 10)]
LAST6 = MONTHS[6:]
LAST3 = MONTHS[9:]


def on(year_month, day):
    return datetime.date(year_month[0], year_month[1], day)


def days_ago(n):
    return AS_OF - datetime.timedelta(days=n)


class Case(object):
    """One synthetic customer, evaluated directly against the real taxonomy.

    Rows go through the same normalisation as the CSV loader (currency,
    counterparty table, merchant codes, restricted categories)."""

    def __init__(self, open_days=700, home_country="US", home_currency="USD"):
        open_date = None if open_days is None else days_ago(open_days)
        self.customer = data_module.Customer("T0001", open_date, home_country or None, home_currency)
        self.txns = []

    def add(self, when, amount, direction, channel, category, counterparty=None, currency="USD", country="US",
            mcc=None, balance=None):
        row = {"txn_id": "R{:06d}".format(len(self.txns) + 1), "posted_date": when.isoformat(),
               "amount": str(amount), "direction": direction, "currency": currency, "channel": channel,
               "category": category, "counterparty": counterparty or "", "txn_country": country or "",
               "mcc": mcc or "", "balance_after": "" if balance is None else str(balance)}
        txn, reason, _ = data_module.normalise_transaction(row, self.customer, TAXONOMY)
        if txn is None:
            raise AssertionError("test row refused: {}".format(reason))
        self.txns.append(txn)
        return self

    def monthly(self, category, amount, direction="debit", channel="internet_banking", months=MONTHS, day=10,
                counterparty=None, currency="USD", country="US"):
        for ym in months:
            self.add(on(ym, day), amount, direction, channel, category, counterparty, currency, country)
        return self

    def salary(self, amount=3000, months=MONTHS, day=25):
        return self.monthly("salary", amount, "credit", "incoming", months, day, "SYN-EMPLOYER-001")

    def purchases(self, year_month, n, each, channel="card_pos", category="groceries", first_day=4, step=2,
                  currency="USD", country="US"):
        for k in range(n):
            self.add(on(year_month, first_day + k * step), each, "debit", channel, category,
                     "SYN-MERCHANT-{:04d}".format(k + 1), currency, country)
        return self

    def data(self):
        return engine.customer_data(TAXONOMY, self.customer, sorted(self.txns, key=lambda t: t.sort_key()))

    def evaluate(self, as_of=AS_OF):
        return evaluate.evaluate_customer(TAXONOMY, self.customer, self.txns, as_of)

    def tags(self, as_of=AS_OF):
        return {tag_id for tag_id, r in self.evaluate(as_of).items() if r.state is True}

    def lifecycle(self, as_of=AS_OF, months=None):
        data = engine.customer_data(TAXONOMY, self.customer,
                                    sorted((t for t in self.txns if t.posted_date <= as_of), key=lambda t: t.sort_key()))
        current = evaluate.evaluate_data(TAXONOMY, data, as_of)
        states = lifecycle_module.checkpoint_states(TAXONOMY, data, as_of, months or TAXONOMY.lifecycle_months,
                                                    current)
        return lifecycle_module.lifecycle(states, current), states


def raw_taxonomy():
    """A fresh, editable copy of tags.json without its hash and changelog, so
    a test can change a rule and load it."""
    raw = taxonomy_module.read_json(engine.DEFAULT_TAXONOMY)
    raw.pop("content_hash", None)
    raw.pop("changelog", None)
    return raw


class CsvFiles(object):
    """Write customers.csv / transactions.csv into a temporary folder."""

    CUSTOMER_COLUMNS = ["customer_id", "display_name", "account_open_date", "home_country", "home_currency"]
    TXN_COLUMNS = ["txn_id", "customer_id", "posted_date", "amount", "currency", "direction", "channel",
                   "category", "counterparty", "txn_country", "mcc", "balance_after"]

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="tagging-test-")
        self.customers = []
        self.txns = []

    def cleanup(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def customer(self, cid, open_date="2024-01-15", home_country="US", home_currency="USD", **extra):
        row = {"customer_id": cid, "display_name": "Synthetic Customer " + cid, "account_open_date": open_date,
               "home_country": home_country, "home_currency": home_currency}
        row.update(extra)
        self.customers.append(row)

    def txn(self, cid, posted_date, amount, direction="", currency="USD", channel="card_pos", category="groceries",
            counterparty="", txn_country="US", txn_id=None, mcc="", balance_after="", **extra):
        row = {"txn_id": txn_id if txn_id is not None else "X{:06d}".format(len(self.txns) + 1),
               "customer_id": cid, "posted_date": posted_date, "amount": amount, "currency": currency,
               "direction": direction, "channel": channel, "category": category, "counterparty": counterparty,
               "txn_country": txn_country, "mcc": mcc, "balance_after": balance_after}
        row.update(extra)
        self.txns.append(row)

    def salary_months(self, cid, amount="3000.00", months=MONTHS, currency="USD", direction="credit"):
        for ym in months:
            self.txn(cid, on(ym, 25).isoformat(), amount, direction, currency, "incoming", "salary", "SYN-EMPLOYER-001")

    def write(self, customer_columns=None, txn_columns=None):
        cpath = os.path.join(self.dir, "customers.csv")
        tpath = os.path.join(self.dir, "transactions.csv")
        ccols = customer_columns or self._columns(self.CUSTOMER_COLUMNS, self.customers)
        tcols = txn_columns or self._columns(self.TXN_COLUMNS, self.txns)
        for path, cols, rows in ((cpath, ccols, self.customers), (tpath, tcols, self.txns)):
            with open(path, "w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
                writer.writeheader()
                for row in rows:
                    writer.writerow(row)
        return cpath, tpath

    @staticmethod
    def _columns(base, rows):
        cols = list(base)
        for row in rows:
            for key in row:
                if key not in cols:
                    cols.append(key)
        return cols

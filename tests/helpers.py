"""Shared test helpers: build one customer's transactions in memory or as CSV files."""

import csv
import datetime
import os
import shutil
import tempfile
from decimal import Decimal

import engine
from engine import data as data_module
from engine import evaluate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAXONOMY = engine.load_taxonomy(engine.DEFAULT_TAXONOMY)
AS_OF = datetime.date(2026, 9, 30)
MONTHS = [(2025, 10), (2025, 11), (2025, 12)] + [(2026, m) for m in range(1, 10)]
LAST6 = MONTHS[6:]
LAST3 = MONTHS[9:]
CENT = Decimal("0.01")


def on(year_month, day):
    return datetime.date(year_month[0], year_month[1], day)


def days_ago(n):
    return AS_OF - datetime.timedelta(days=n)


class Case(object):
    """One synthetic customer, evaluated directly against the real taxonomy."""

    def __init__(self, open_days=700, home_country="US", home_currency="USD"):
        open_date = None if open_days is None else days_ago(open_days)
        self.customer = data_module.Customer("T0001", open_date, home_country or None, home_currency)
        self.txns = []

    def add(self, when, amount, direction, channel, category, counterparty=None, currency="USD", country="US"):
        base = (Decimal(str(amount)) * TAXONOMY.fx_rates[currency]).quantize(CENT)
        self.txns.append(data_module.Transaction(
            None, "T0001", when, direction, base, currency, channel, category, counterparty, country))
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

    def evaluate(self, as_of=AS_OF):
        txns = sorted(self.txns, key=lambda t: (t.posted_date, t.direction, t.amount_base))
        return evaluate.evaluate_customer(TAXONOMY, self.customer, txns, as_of)

    def tags(self, as_of=AS_OF):
        return {tag_id for tag_id, r in self.evaluate(as_of).items() if r.state is True}


class CsvFiles(object):
    """Write customers.csv / transactions.csv into a temporary folder."""

    CUSTOMER_COLUMNS = ["customer_id", "display_name", "account_open_date", "home_country", "home_currency"]
    TXN_COLUMNS = ["txn_id", "customer_id", "posted_date", "amount", "currency", "direction", "channel",
                   "category", "counterparty", "txn_country"]

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
            counterparty="", txn_country="US", txn_id=None, **extra):
        row = {"txn_id": txn_id if txn_id is not None else "X{:06d}".format(len(self.txns) + 1),
               "customer_id": cid, "posted_date": posted_date, "amount": amount, "currency": currency,
               "direction": direction, "channel": channel, "category": category, "counterparty": counterparty,
               "txn_country": txn_country}
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

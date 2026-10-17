"""Load and normalise customers.csv and transactions.csv.

Data contract (see README):

customers.csv
    customer_id        required, unique
    account_open_date  YYYY-MM-DD; needed by tenure rules
    home_country       ISO 3166 alpha-2; needed by "abroad" rules
    home_currency      ISO 4217; defaults to the base currency
    Any other column is ignored and never loaded.

transactions.csv
    txn_id         unique when present; later duplicates are skipped
    customer_id    required; must exist in customers.csv
    posted_date    required, YYYY-MM-DD
    amount         required, decimal; see sign handling below
    currency       ISO 4217; empty means the customer's home currency
    direction      credit or debit (also cr/dr, c/d); empty means use the sign
    channel        e.g. mobile_app, card_pos, branch; empty means "unknown"
    category       e.g. salary, rent, cash_withdrawal; empty means "uncategorized"
    counterparty   synthetic payer or merchant id; optional
    txn_country    ISO 3166 alpha-2 where the transaction happened; optional

Sign handling: with a direction, the amount may be unsigned or signed with
money out negative; a negative credit is a contradiction and is skipped.
Without a direction, a negative amount is a debit and a positive amount a
credit. Zero amounts are skipped.

Currency handling: amounts are converted to the base currency with the fixed
rate table in the taxonomy settings. An unknown currency is skipped, never
guessed. Every skipped row is counted by reason in the data notes.
"""

import csv
import datetime
from collections import Counter, OrderedDict
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN

from . import policy


class DataError(ValueError):
    """The input files cannot be used at all (e.g. a required column is missing)."""


CENT = Decimal("0.01")

_CREDIT = {"credit", "cr", "c"}
_DEBIT = {"debit", "dr", "d"}


class Customer(object):
    __slots__ = ("customer_id", "account_open_date", "home_country", "home_currency")

    def __init__(self, customer_id, account_open_date, home_country, home_currency):
        self.customer_id = customer_id
        self.account_open_date = account_open_date
        self.home_country = home_country
        self.home_currency = home_currency


class Transaction(object):
    __slots__ = (
        "txn_id", "customer_id", "posted_date", "direction", "amount_base",
        "currency", "channel", "category", "counterparty", "txn_country",
    )

    def __init__(self, txn_id, customer_id, posted_date, direction, amount_base,
                 currency, channel, category, counterparty, txn_country):
        self.txn_id = txn_id
        self.customer_id = customer_id
        self.posted_date = posted_date
        self.direction = direction
        self.amount_base = amount_base
        self.currency = currency
        self.channel = channel
        self.category = category
        self.counterparty = counterparty
        self.txn_country = txn_country

    def field(self, name):
        return getattr(self, name)


def parse_date(text):
    text = (text or "").strip()
    if not text:
        return None
    try:
        return datetime.datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _read_rows(path, wanted, required):
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        header = [h.strip() for h in (reader.fieldnames or [])]
        missing = [c for c in required if c not in header]
        if missing:
            raise DataError("{}: missing required column(s): {}".format(path, ", ".join(missing)))
        ignored = sorted(h for h in header if h and h not in wanted)
        rows = []
        for raw in reader:
            row = {}
            for key, value in raw.items():
                if key is None:
                    continue
                key = key.strip()
                if key in wanted:
                    row[key] = (value or "").strip()
            rows.append(row)
    return rows, ignored


def load_customers(path, base_currency):
    """Return (customers by id, notes). Only policy.CUSTOMER_COLUMNS are read."""
    rows, ignored = _read_rows(path, policy.CUSTOMER_COLUMNS, ("customer_id",))
    customers = OrderedDict()
    problems = Counter()
    for row in rows:
        cid = row.get("customer_id", "")
        if not cid:
            problems["missing_customer_id"] += 1
            continue
        if cid in customers:
            problems["duplicate_customer_id"] += 1
            continue
        open_text = row.get("account_open_date", "")
        open_date = parse_date(open_text)
        if open_text and open_date is None:
            problems["bad_account_open_date"] += 1
        country = row.get("home_country", "").upper() or None
        currency = row.get("home_currency", "").upper() or base_currency
        customers[cid] = Customer(cid, open_date, country, currency)
    ordered = OrderedDict((cid, customers[cid]) for cid in sorted(customers))
    notes = {
        "customers_read": len(rows),
        "customers_used": len(ordered),
        "problems": dict(sorted(problems.items())),
        "ignored_columns": ignored,
    }
    return ordered, notes


def _parse_amount(text):
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite():
        return None
    return value


def normalise_transaction(row, customer, fx_rates):
    """Return (Transaction, None, defaulted_currency) or (None, skip_reason, False)."""
    posted = parse_date(row.get("posted_date", ""))
    if posted is None:
        return None, "bad_or_missing_date", False
    amount = _parse_amount(row.get("amount", ""))
    if amount is None:
        return None, "bad_or_missing_amount", False
    if amount == 0:
        return None, "zero_amount", False

    direction_text = row.get("direction", "").lower()
    if direction_text in _CREDIT:
        direction = "credit"
        if amount < 0:
            return None, "sign_conflict", False
    elif direction_text in _DEBIT:
        direction = "debit"
    elif direction_text == "":
        direction = "debit" if amount < 0 else "credit"
    else:
        return None, "bad_direction", False

    currency = row.get("currency", "").upper()
    defaulted = False
    if not currency:
        currency = customer.home_currency
        defaulted = True
    rate = fx_rates.get(currency)
    if rate is None:
        return None, "unknown_currency", False
    amount_base = (abs(amount) * rate).quantize(CENT, rounding=ROUND_HALF_EVEN)
    if amount_base == 0:
        return None, "zero_amount", False

    txn = Transaction(
        txn_id=row.get("txn_id", "") or None,
        customer_id=customer.customer_id,
        posted_date=posted,
        direction=direction,
        amount_base=amount_base,
        currency=currency,
        channel=row.get("channel", "").lower() or "unknown",
        category=row.get("category", "").lower() or "uncategorized",
        counterparty=row.get("counterparty", "") or None,
        txn_country=row.get("txn_country", "").upper() or None,
    )
    return txn, None, defaulted


def load_transactions(path, customers, fx_rates, as_of=None):
    """Read, normalise and window transactions.

    Returns (transactions by customer id, as_of date, run notes, per-customer notes).
    When as_of is None it defaults to the latest valid posted_date in the file,
    never the wall clock, so the same files always give the same result.
    """
    rows, ignored = _read_rows(
        path, policy.TRANSACTION_COLUMNS, ("customer_id", "posted_date", "amount")
    )
    run_skips = Counter()
    per_customer = {cid: {"skipped": Counter(), "currency_defaulted": 0} for cid in customers}
    valid = []
    seen_ids = set()
    for row in rows:
        cid = row.get("customer_id", "")
        customer = customers.get(cid)
        if customer is None:
            run_skips["unknown_customer"] += 1
            continue
        txn, reason, defaulted = normalise_transaction(row, customer, fx_rates)
        if txn is None:
            run_skips[reason] += 1
            per_customer[cid]["skipped"][reason] += 1
            continue
        if txn.txn_id is not None:
            if txn.txn_id in seen_ids:
                run_skips["duplicate_txn_id"] += 1
                per_customer[cid]["skipped"]["duplicate_txn_id"] += 1
                continue
            seen_ids.add(txn.txn_id)
        if defaulted:
            per_customer[cid]["currency_defaulted"] += 1
        valid.append(txn)

    if as_of is None:
        if not valid:
            raise DataError("no usable transactions: pass an explicit as-of date")
        as_of = max(t.posted_date for t in valid)

    by_customer = OrderedDict((cid, []) for cid in customers)
    after = 0
    for txn in valid:
        if txn.posted_date > as_of:
            after += 1
            per_customer[txn.customer_id]["skipped"]["after_as_of"] += 1
            continue
        by_customer[txn.customer_id].append(txn)
    for cid in by_customer:
        by_customer[cid].sort(key=lambda t: (t.posted_date, t.txn_id or "", t.direction, t.amount_base))
    if after:
        run_skips["after_as_of"] += after

    used = sum(len(v) for v in by_customer.values())
    run_notes = {
        "transactions_read": len(rows),
        "transactions_used": used,
        "skipped": dict(sorted(run_skips.items())),
        "ignored_columns": ignored,
    }
    customer_notes = {}
    for cid, info in per_customer.items():
        customer_notes[cid] = {
            "transactions_used": len(by_customer[cid]),
            "skipped": dict(sorted(info["skipped"].items())),
            "currency_defaulted": info["currency_defaulted"],
        }
    return by_customer, as_of, run_notes, customer_notes

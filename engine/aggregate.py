"""Feature buckets: per customer, per feature and per calendar month.

A *feature* is a transaction selector (one or more filters that must all
match) plus what to track about the matching transactions. The taxonomy's
rules are compiled into a fixed set of features (see features_for). For
every customer and calendar month the engine keeps one bucket per feature:

    n, total, max, credit, debit   counts and whole cents in the base currency
    last_day                       the latest posted date in the month
    distinct                       distinct values of the requested fields
    streams                        per counterparty: [count, total cents]
    balance                        lowest and closing balance (balance feature)

A window that covers whole months is answered from the buckets alone; a
window edge that cuts a month in two is answered from that month's
transactions. Buckets are always recomputed from a month's transactions,
never patched, so batch runs and incremental updates produce identical
buckets (see DESIGN.md).
"""

import datetime
import hashlib
import json
from collections import OrderedDict

from . import windows

BALANCE_KEY = "balance"


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class FeatureSpec(object):
    """A compiled feature: key, the filters that must all match, and what to track."""

    __slots__ = ("key", "filters", "distinct_fields", "streams", "balance", "predicate", "needs_customer")

    def __init__(self, key, filters, distinct_fields=(), streams=False, balance=False):
        self.key = key
        self.filters = filters
        self.distinct_fields = tuple(sorted(distinct_fields))
        self.streams = streams
        self.balance = balance
        self.predicate, self.needs_customer = compile_filters(filters)

    def definition(self):
        return OrderedDict([
            ("filters", self.filters),
            ("distinct_fields", list(self.distinct_fields)),
            ("streams", self.streams),
            ("balance", self.balance),
        ])


def _matcher(field, matcher):
    if field == "is_foreign_currency":
        def check(txn, customer):
            return (txn.currency != customer.home_currency) == matcher
        return check, True
    if field == "is_foreign_country":
        def check(txn, customer):
            if txn.txn_country is None or customer.home_country is None:
                return False
            return (txn.txn_country != customer.home_country) == matcher
        return check, True
    if isinstance(matcher, dict):
        excluded = frozenset(matcher["not_in"])

        def check(txn, customer):
            value = getattr(txn, field)
            return value is None or value not in excluded
        return check, False
    if isinstance(matcher, list):
        allowed = frozenset(matcher)

        def check(txn, customer):
            return getattr(txn, field) in allowed
        return check, False

    def check(txn, customer):
        return getattr(txn, field) == matcher
    return check, False


def compile_filters(filters):
    """Compile a list of filter objects (all must match) into predicate(txn, customer)."""
    checks = []
    needs_customer = False
    for flt in filters:
        for field in sorted(flt):
            check, uses_customer = _matcher(field, flt[field])
            checks.append(check)
            needs_customer = needs_customer or uses_customer
    if not checks:
        return (lambda txn, customer: True), False
    if len(checks) == 1:
        return checks[0], needs_customer
    checks = tuple(checks)

    def predicate(txn, customer):
        for check in checks:
            if not check(txn, customer):
                return False
        return True
    return predicate, needs_customer


def normalise_filters(filters):
    """Canonical list form: drop empty filters, sort keys, sort and dedupe the list."""
    seen = OrderedDict()
    for flt in filters:
        if not flt:
            continue
        text = canonical_json(flt)
        seen[text] = json.loads(text)
    return [seen[k] for k in sorted(seen)]


def feature_key(filters, distinct_fields=(), streams=False, balance=False):
    if balance:
        return BALANCE_KEY
    payload = canonical_json({"filters": normalise_filters(filters)})
    return "f_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class FeatureSet(object):
    """All features a taxonomy needs, keyed by feature key."""

    def __init__(self):
        self._raw = OrderedDict()

    def request(self, filters, distinct_field=None, streams=False, balance=False):
        """Register a feature and return its key. Requests for the same filters merge."""
        filters = normalise_filters(filters)
        key = feature_key(filters, balance=balance)
        entry = self._raw.setdefault(key, {"filters": [] if balance else filters, "distinct": set(),
                                           "streams": False, "balance": balance})
        if distinct_field:
            entry["distinct"].add(distinct_field)
        entry["streams"] = entry["streams"] or streams
        return key

    def build(self):
        specs = OrderedDict()
        for key in sorted(self._raw):
            raw = self._raw[key]
            specs[key] = FeatureSpec(key, raw["filters"], sorted(raw["distinct"]), raw["streams"], raw["balance"])
        return specs


class Agg(object):
    """Aggregates over a set of transactions (one bucket, or a combined window)."""

    __slots__ = ("n", "total", "max", "credit", "debit", "last_day", "distinct", "streams",
                 "bal_min", "bal_end", "bal_end_key", "bal_n")

    def __init__(self):
        self.n = 0
        self.total = 0
        self.max = 0
        self.credit = 0
        self.debit = 0
        self.last_day = None
        self.distinct = None
        self.streams = None
        self.bal_min = None
        self.bal_end = None
        self.bal_end_key = None
        self.bal_n = 0

    def add(self, txn, spec):
        cents = txn.amount_cents
        self.n += 1
        self.total += cents
        if cents > self.max:
            self.max = cents
        if txn.direction == "credit":
            self.credit += cents
        else:
            self.debit += cents
        if self.last_day is None or txn.posted_date > self.last_day:
            self.last_day = txn.posted_date
        if spec.distinct_fields:
            if self.distinct is None:
                self.distinct = {f: set() for f in spec.distinct_fields}
            for f in spec.distinct_fields:
                value = getattr(txn, f)
                if value:
                    self.distinct[f].add(value)
        if spec.streams and txn.counterparty:
            if self.streams is None:
                self.streams = {}
            entry = self.streams.get(txn.counterparty)
            if entry is None:
                self.streams[txn.counterparty] = [1, cents]
            else:
                entry[0] += 1
                entry[1] += cents
        if spec.balance and txn.balance_cents is not None:
            balance = txn.balance_cents
            self.bal_n += 1
            if self.bal_min is None or balance < self.bal_min:
                self.bal_min = balance
            key = txn.sort_key()
            if self.bal_end_key is None or key > self.bal_end_key:
                self.bal_end_key = key
                self.bal_end = balance

    def merge(self, other):
        """Fold another Agg into this one (used to combine months into a window)."""
        if other is None or other.n == 0:
            return self
        self.n += other.n
        self.total += other.total
        if other.max > self.max:
            self.max = other.max
        self.credit += other.credit
        self.debit += other.debit
        if other.last_day is not None and (self.last_day is None or other.last_day > self.last_day):
            self.last_day = other.last_day
        if other.distinct is not None:
            if self.distinct is None:
                self.distinct = {f: set() for f in other.distinct}
            for f, values in other.distinct.items():
                self.distinct.setdefault(f, set()).update(values)
        if other.streams is not None:
            if self.streams is None:
                self.streams = {}
            for cp, (count, total) in other.streams.items():
                entry = self.streams.get(cp)
                if entry is None:
                    self.streams[cp] = [count, total]
                else:
                    entry[0] += count
                    entry[1] += total
        if other.bal_n:
            self.bal_n += other.bal_n
            if self.bal_min is None or other.bal_min < self.bal_min:
                self.bal_min = other.bal_min
            if self.bal_end_key is None or other.bal_end_key > self.bal_end_key:
                self.bal_end_key = other.bal_end_key
                self.bal_end = other.bal_end
        return self

    # -- persistence (the profile store keeps buckets as rows) ---------------
    def to_record(self):
        extra = OrderedDict()
        if self.distinct is not None:
            extra["distinct"] = OrderedDict((f, sorted(v)) for f, v in sorted(self.distinct.items()))
        if self.streams is not None:
            extra["streams"] = OrderedDict((cp, list(v)) for cp, v in sorted(self.streams.items()))
        if self.bal_n:
            extra["balance"] = OrderedDict([
                ("min", self.bal_min), ("end", self.bal_end), ("n", self.bal_n),
                ("end_key", [self.bal_end_key[0].isoformat(), self.bal_end_key[1], self.bal_end_key[2],
                             self.bal_end_key[3]]),
            ])
        return OrderedDict([
            ("n", self.n), ("total", self.total), ("max", self.max), ("credit", self.credit),
            ("debit", self.debit), ("last_day", self.last_day.isoformat() if self.last_day else None),
            ("extra", canonical_json(extra)),
        ])

    @classmethod
    def from_record(cls, record):
        agg = cls()
        agg.n = record["n"]
        agg.total = record["total"]
        agg.max = record["max"]
        agg.credit = record["credit"]
        agg.debit = record["debit"]
        last = record["last_day"]
        agg.last_day = datetime.date.fromisoformat(last) if last else None
        extra = json.loads(record["extra"]) if record["extra"] else {}
        if "distinct" in extra:
            agg.distinct = {f: set(v) for f, v in extra["distinct"].items()}
        if "streams" in extra:
            agg.streams = {cp: list(v) for cp, v in extra["streams"].items()}
        if "balance" in extra:
            bal = extra["balance"]
            agg.bal_min = bal["min"]
            agg.bal_end = bal["end"]
            agg.bal_n = bal["n"]
            key = bal["end_key"]
            agg.bal_end_key = (datetime.date.fromisoformat(key[0]), key[1], key[2], key[3])
        return agg


EMPTY = Agg()


def month_of(day):
    return (day.year, day.month)


def aggregate(rows, spec, customer_for):
    """One Agg over rows for spec. customer_for(txn) gives the customer
    attributes in force for that transaction."""
    agg = Agg()
    predicate = spec.predicate
    for txn in rows:
        if spec.balance:
            if txn.balance_cents is not None:
                agg.add(txn, spec)
            continue
        if predicate(txn, customer_for(txn) if spec.needs_customer else None):
            agg.add(txn, spec)
    return agg


def month_buckets(rows, specs, customer_for):
    """Every non-empty bucket for rows that all fall in one calendar month:
    {feature key: Agg}."""
    buckets = OrderedDict()
    for key, spec in specs.items():
        agg = aggregate(rows, spec, customer_for)
        if agg.n:
            buckets[key] = agg
    return buckets


class CustomerData(object):
    """One customer's transactions and buckets, as the evaluator reads them.

    rows_by_month: {(year, month): [Transaction, ...]} sorted by sort_key.
    buckets:       {(year, month): {feature key: Agg}}; months missing from it
                   are computed from rows_by_month on first use.
    customer_for:  callable(txn) -> the customer attributes for that
                   transaction (versioned attributes in the profile store).
    """

    def __init__(self, customer, rows_by_month, specs, buckets=None, customer_for=None):
        self.customer = customer
        self.rows_by_month = rows_by_month
        self.specs = specs
        self.buckets = buckets if buckets is not None else {}
        self.customer_for = customer_for or (lambda txn: customer)
        self._range_cache = {}

    @classmethod
    def from_rows(cls, customer, rows, specs, customer_for=None):
        by_month = OrderedDict()
        for txn in rows:
            by_month.setdefault(month_of(txn.posted_date), []).append(txn)
        return cls(customer, by_month, specs, customer_for=customer_for)

    def month_bucket(self, key, year_month):
        month = self.buckets.get(year_month)
        if month is None:
            rows = self.rows_by_month.get(year_month)
            month = month_buckets(rows, self.specs, self.customer_for) if rows else {}
            self.buckets[year_month] = month
        return month.get(key)

    def range_agg(self, key, start, end):
        """Combined Agg for feature key over [start, end] (dates, inclusive)."""
        cache_key = (key, start, end)
        cached = self._range_cache.get(cache_key)
        if cached is not None:
            return cached
        total = Agg()
        spec = self.specs[key]
        year, month = start.year, start.month
        while (year, month) <= (end.year, end.month):
            first, last = windows.month_bounds((year, month))
            if start <= first and last <= end:
                total.merge(self.month_bucket(key, (year, month)))
            else:
                rows = [t for t in self.rows_by_month.get((year, month), ()) if start <= t.posted_date <= end]
                if rows:
                    total.merge(aggregate(rows, spec, self.customer_for))
            month += 1
            if month == 13:
                year, month = year + 1, 1
        self._range_cache[cache_key] = total
        return total

    def all_buckets(self):
        """Every bucket for every month with transactions: {(ym, key): Agg}."""
        out = OrderedDict()
        for ym in sorted(self.rows_by_month):
            for key in self.specs:
                agg = self.month_bucket(key, ym)
                if agg is not None and agg.n:
                    out[(ym, key)] = agg
        return out

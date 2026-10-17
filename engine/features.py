"""Compute one rule leaf's value for one customer.

Every function returns a Measured: the value, the window(s) it covered, the
details shown as evidence and, when an input field the leaf needs is
missing, the list of missing fields (the condition is then "unknown",
never guessed).
"""

from collections import OrderedDict
from decimal import Decimal

from . import windows

ZERO = Decimal(0)


class Measured(object):
    __slots__ = ("value", "window", "details", "missing", "note")

    def __init__(self, value, window=None, details=None, missing=(), note=None):
        self.value = value
        self.window = window
        self.details = details or OrderedDict()
        self.missing = sorted(set(missing))
        self.note = note


class Context(object):
    """Everything a leaf may read: one customer, their transactions, as_of."""

    def __init__(self, customer, txns, as_of, tag_states=None, tag_missing=None):
        self.customer = customer
        self.txns = txns
        self.as_of = as_of
        self.tag_states = tag_states if tag_states is not None else {}
        self.tag_missing = tag_missing if tag_missing is not None else {}


def txn_matches(txn, flt, customer):
    for field, matcher in flt.items():
        if field == "is_foreign_currency":
            if (txn.currency != customer.home_currency) != matcher:
                return False
            continue
        if field == "is_foreign_country":
            if txn.txn_country is None or customer.home_country is None:
                return False
            if (txn.txn_country != customer.home_country) != matcher:
                return False
            continue
        value = txn.field(field)
        if isinstance(matcher, dict):
            if value is not None and value in matcher["not_in"]:
                return False
        elif isinstance(matcher, list):
            if value not in matcher:
                return False
        elif value != matcher:
            return False
    return True


def filter_missing(flt, customer):
    if flt and "is_foreign_country" in flt and customer.home_country is None:
        return ["customers.home_country"]
    return []


def _select(ctx, flt, window):
    return [
        t for t in ctx.txns
        if window.contains(t.posted_date) and txn_matches(t, flt, ctx.customer)
    ]


def _total(rows):
    total = ZERO
    for t in rows:
        total += t.amount_base
    return total


def scalar(ctx, spec):
    flt = spec.get("filter", {})
    window = windows.resolve(spec["window"], ctx.as_of)
    missing = filter_missing(flt, ctx.customer)
    if missing:
        return Measured(None, window, missing=missing)
    rows = _select(ctx, flt, window)
    metric = spec["metric"]
    if metric == "count":
        value = len(rows)
    elif metric == "sum":
        value = _total(rows)
    elif metric == "max":
        value = max([t.amount_base for t in rows] or [ZERO])
    elif metric == "count_per_month":
        value = Decimal(len(rows)) / window.length_in_months
    elif metric == "sum_per_month":
        value = _total(rows) / window.length_in_months
    else:  # pragma: no cover - guarded by taxonomy validation
        raise ValueError(metric)
    details = OrderedDict([("transactions", len(rows))])
    return Measured(value, window, details)


def compare(value, op, threshold):
    if op == ">=":
        return value >= threshold
    if op == ">":
        return value > threshold
    if op == "<=":
        return value <= threshold
    if op == "<":
        return value < threshold
    if op == "==":
        return value == threshold
    raise ValueError(op)  # pragma: no cover


def _median(values):
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def months_where(ctx, leaf):
    flt = leaf.get("filter", {})
    window = windows.resolve(leaf["window"], ctx.as_of)
    missing = filter_missing(flt, ctx.customer)
    if missing:
        return Measured(None, window, missing=missing)
    buckets = OrderedDict((ym, {"count": 0, "sum": ZERO, "credit": ZERO, "debit": ZERO}) for ym in window.months)
    for t in _select(ctx, flt, window):
        bucket = buckets[(t.posted_date.year, t.posted_date.month)]
        bucket["count"] += 1
        bucket["sum"] += t.amount_base
        bucket[t.direction] += t.amount_base

    monthly = leaf["monthly"]
    measure = monthly["measure"]
    threshold = Decimal(str(monthly["value"]))
    median = None
    if measure == "deviation_from_median":
        nonzero = [b["sum"] for b in buckets.values() if b["sum"] > 0]
        median = _median(nonzero) if nonzero else None

    met = []
    for ym, bucket in buckets.items():
        if measure == "count":
            value = Decimal(bucket["count"])
        elif measure == "sum":
            value = bucket["sum"]
        elif measure == "net_flow":
            value = bucket["credit"] - bucket["debit"]
        elif measure == "net_flow_ratio":
            value = None if bucket["credit"] == 0 else (bucket["credit"] - bucket["debit"]) / bucket["credit"]
        else:  # deviation_from_median
            value = None if median is None else abs(bucket["sum"] - median) / median
        if value is not None and compare(value, monthly["op"], threshold):
            met.append("{:04d}-{:02d}".format(*ym))
    details = OrderedDict([("months_met", met)])
    if median is not None:
        details["median_month"] = median
    return Measured(len(met), window, details)


def distinct(ctx, leaf):
    flt = leaf.get("filter", {})
    window = windows.resolve(leaf["window"], ctx.as_of)
    missing = filter_missing(flt, ctx.customer)
    if missing:
        return Measured(None, window, missing=missing)
    values = set()
    for t in _select(ctx, flt, window):
        value = t.field(leaf["field"])
        if value:
            values.add(value)
    return Measured(len(values), window, OrderedDict([("distinct_values", len(values))]))


def share(ctx, leaf):
    window = windows.resolve(leaf["window"], ctx.as_of)
    missing = filter_missing(leaf.get("filter", {}), ctx.customer) + filter_missing(leaf["of"], ctx.customer)
    if missing:
        return Measured(None, window, missing=missing)
    base_rows = _select(ctx, leaf["of"], window)
    part_rows = [t for t in base_rows if txn_matches(t, leaf.get("filter", {}), ctx.customer)]
    if leaf["by"] == "count":
        numerator, denominator = Decimal(len(part_rows)), Decimal(len(base_rows))
    else:
        numerator, denominator = _total(part_rows), _total(base_rows)
    value = numerator / denominator if denominator > 0 else ZERO
    details = OrderedDict([("numerator", numerator), ("denominator", denominator)])
    return Measured(value, window, details)


def ratio(ctx, leaf):
    top = scalar(ctx, leaf["numerator"])
    bottom = scalar(ctx, leaf["denominator"])
    details = OrderedDict([
        ("numerator", top.value),
        ("numerator_window", top.window.label()),
        ("denominator", bottom.value),
        ("denominator_window", bottom.window.label()),
    ])
    missing = top.missing + bottom.missing
    if missing:
        return Measured(None, top.window, details, missing=missing)
    minimum = Decimal(str(leaf.get("min_denominator", 0)))
    if bottom.value == 0 or bottom.value < minimum:
        note = "the earlier level is below the minimum needed to compare"
        return Measured(None, top.window, details, note=note)
    return Measured(Decimal(top.value) / Decimal(bottom.value), top.window, details)


def tenure_days(ctx, leaf):
    opened = ctx.customer.account_open_date
    if opened is None:
        return Measured(None, missing=["customers.account_open_date"])
    if opened > ctx.as_of:
        return Measured(None, note="the account was opened after the as-of date")
    return Measured((ctx.as_of - opened).days, details=OrderedDict([("account_open_date", opened.isoformat())]))


def tag_state(ctx, leaf):
    state = ctx.tag_states[leaf["tag"]]
    if state is None:
        return Measured(None, missing=ctx.tag_missing.get(leaf["tag"], []))
    return Measured(state)


def measure(ctx, leaf):
    metric = leaf["metric"]
    if metric in ("count", "sum", "max", "count_per_month", "sum_per_month"):
        return scalar(ctx, leaf)
    if metric == "months_where":
        return months_where(ctx, leaf)
    if metric == "distinct":
        return distinct(ctx, leaf)
    if metric == "share":
        return share(ctx, leaf)
    if metric == "ratio":
        return ratio(ctx, leaf)
    if metric == "tenure_days":
        return tenure_days(ctx, leaf)
    if metric == "tag":
        return tag_state(ctx, leaf)
    raise ValueError(metric)  # pragma: no cover

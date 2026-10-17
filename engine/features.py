"""Compute one rule leaf's value for one customer from the feature buckets.

Every function returns a Measured: the value, the window it covered, the
details shown as evidence and, when an input field the leaf needs is
missing, the list of missing fields (the condition is then "unknown",
never guessed).

Amounts are kept as whole cents in the buckets and turned into Decimal
currency units here, so the decision and the evidence use the same numbers.
"""

import datetime
from collections import OrderedDict
from decimal import Decimal

from . import aggregate
from . import windows

ZERO = Decimal(0)
HUNDRED = Decimal(100)


def units(cents):
    return Decimal(cents) / HUNDRED


class Measured(object):
    __slots__ = ("value", "window", "details", "missing", "note", "lines")

    def __init__(self, value, window=None, details=None, missing=(), note=None, lines=None):
        self.value = value
        self.window = window
        self.details = details if details is not None else {}
        self.missing = sorted(set(missing)) if missing else []
        self.note = note
        self.lines = lines or []


class Context(object):
    """Everything a leaf may read: one customer's data, the as-of date and
    the states of tags already evaluated."""

    def __init__(self, taxonomy, data, as_of, tag_states=None, tag_missing=None):
        self.taxonomy = taxonomy
        self.data = data
        self.customer = data.customer
        self.as_of = as_of
        self.tag_states = tag_states if tag_states is not None else {}
        self.tag_missing = tag_missing if tag_missing is not None else {}
        self.tag_id = None
        self._has_balance = None

    def key(self, leaf_id, role="main"):
        return self.taxonomy.leaf_features[(self.tag_id, leaf_id, role)]

    def has_balance(self):
        if self._has_balance is None:
            self._has_balance = any(
                txn.balance_cents is not None
                for rows in self.data.rows_by_month.values() for txn in rows
            ) or any(
                aggregate.BALANCE_KEY in month and month[aggregate.BALANCE_KEY].bal_n
                for month in self.data.buckets.values()
            )
        return self._has_balance


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


def filter_missing(flt, customer):
    if flt and "is_foreign_country" in flt and customer.home_country is None:
        return ["customers.home_country"]
    return []


def _median(values):
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _scalar_value(metric, agg, window):
    if metric == "count":
        return agg.n
    if metric == "sum":
        return units(agg.total)
    if metric == "max":
        return units(agg.max)
    if metric == "count_per_month":
        return Decimal(agg.n) / window.length_in_months
    if metric == "sum_per_month":
        return units(agg.total) / window.length_in_months
    raise ValueError(metric)  # pragma: no cover


def scalar(ctx, leaf, role="main", spec=None):
    spec = spec or leaf
    flt = spec.get("filter", {})
    window = windows.resolve(spec["window"], ctx.as_of)
    missing = filter_missing(flt, ctx.customer)
    if missing:
        return Measured(None, window, missing=missing)
    agg = ctx.data.range_agg(ctx.key(leaf["id"], role), window.start, window.end)
    value = _scalar_value(spec["metric"], agg, window)
    return Measured(value, window, OrderedDict([("transactions", agg.n)]))


def _balance_before(ctx, year_month):
    """The closing balance of the latest month before year_month with balance data, or None."""
    earlier = sorted((ym for ym in ctx.data.rows_by_month if ym < year_month), reverse=True)
    earlier_buckets = sorted((ym for ym in ctx.data.buckets if ym < year_month and ym not in ctx.data.rows_by_month),
                             reverse=True)
    for ym in sorted(set(earlier) | set(earlier_buckets), reverse=True):
        bucket = ctx.data.month_bucket(aggregate.BALANCE_KEY, ym)
        if bucket is not None and bucket.bal_n:
            return bucket.bal_end
    return None


def _month_balance(ctx, year_month, carried):
    """(lowest, closing) balance in cents for a complete month, carrying the
    previous closing balance through months with no balance data."""
    bucket = ctx.data.month_bucket(aggregate.BALANCE_KEY, year_month)
    if bucket is None or not bucket.bal_n:
        return carried, carried
    lowest = bucket.bal_min if carried is None else min(bucket.bal_min, carried)
    return lowest, bucket.bal_end


def months_where(ctx, leaf):
    flt = leaf.get("filter", {})
    window = windows.resolve(leaf["window"], ctx.as_of)
    missing = filter_missing(flt, ctx.customer)
    monthly = leaf["monthly"]
    measure = monthly["measure"]
    balance = measure in ("min_balance", "end_balance")
    if balance and not ctx.has_balance():
        missing = missing + ["transactions.balance_after"]
    if missing:
        return Measured(None, window, missing=missing)

    op = monthly["op"]
    labels = window.month_labels
    met = []
    median = None
    if balance:
        threshold = Decimal(str(monthly["value"]))
        carried = _balance_before(ctx, window.months[0])
        for index, ym in enumerate(window.months):
            lowest, closing = _month_balance(ctx, ym, carried)
            carried = closing
            chosen = lowest if measure == "min_balance" else closing
            if chosen is not None and compare(units(chosen), op, threshold):
                met.append(labels[index])
    else:
        key = ctx.key(leaf["id"])
        month_bucket = ctx.data.month_bucket
        buckets = [month_bucket(key, ym) for ym in window.months]
        if measure == "count":
            # Counts are whole numbers: compare as integers, no Decimal needed.
            threshold = Decimal(str(monthly["value"]))
            for index, bucket in enumerate(buckets):
                if compare(bucket.n if bucket is not None else 0, op, threshold):
                    met.append(labels[index])
        else:
            threshold = Decimal(str(monthly["value"]))
            if measure == "deviation_from_median":
                nonzero = [units(b.total) for b in buckets if b is not None and b.total > 0]
                median = _median(nonzero) if nonzero else None
            for index, bucket in enumerate(buckets):
                bucket = bucket or aggregate.EMPTY
                if measure == "sum":
                    value = units(bucket.total)
                elif measure == "net_flow":
                    value = units(bucket.credit - bucket.debit)
                elif measure == "net_flow_ratio":
                    value = None if bucket.credit == 0 else \
                        Decimal(bucket.credit - bucket.debit) / Decimal(bucket.credit)
                else:  # deviation_from_median
                    value = None if median is None else abs(units(bucket.total) - median) / median
                if value is not None and compare(value, op, threshold):
                    met.append(labels[index])
    details = {"months_met": met}
    if median is not None:
        details["median_month"] = median
    return Measured(len(met), window, details)


def distinct(ctx, leaf):
    flt = leaf.get("filter", {})
    window = windows.resolve(leaf["window"], ctx.as_of)
    missing = filter_missing(flt, ctx.customer)
    if missing:
        return Measured(None, window, missing=missing)
    agg = ctx.data.range_agg(ctx.key(leaf["id"]), window.start, window.end)
    values = agg.distinct.get(leaf["field"], set()) if agg.distinct else set()
    return Measured(len(values), window, OrderedDict([("distinct_values", len(values))]))


def share(ctx, leaf):
    window = windows.resolve(leaf["window"], ctx.as_of)
    missing = filter_missing(leaf.get("filter", {}), ctx.customer) + filter_missing(leaf["of"], ctx.customer)
    if missing:
        return Measured(None, window, missing=missing)
    base = ctx.data.range_agg(ctx.key(leaf["id"], "of"), window.start, window.end)
    part = ctx.data.range_agg(ctx.key(leaf["id"], "part"), window.start, window.end)
    if leaf["by"] == "count":
        numerator, denominator = Decimal(part.n), Decimal(base.n)
    else:
        numerator, denominator = units(part.total), units(base.total)
    value = numerator / denominator if denominator > 0 else ZERO
    details = OrderedDict([("numerator", numerator), ("denominator", denominator)])
    return Measured(value, window, details)


def _part(ctx, leaf, role):
    spec = leaf[role]
    if spec["metric"] == "balance":
        return balance(ctx, spec)
    return scalar(ctx, leaf, role, spec)


def ratio(ctx, leaf):
    top = _part(ctx, leaf, "numerator")
    bottom = _part(ctx, leaf, "denominator")
    details = OrderedDict([
        ("numerator", top.value),
        ("numerator_window", top.window.label()),
        ("denominator", bottom.value),
        ("denominator_window", bottom.window.label()),
    ])
    missing = top.missing + bottom.missing
    if missing:
        return Measured(None, top.window, details, missing=missing)
    if top.value is None or bottom.value is None:
        return Measured(None, top.window, details, note=top.note or bottom.note)
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
    lines = ["account opened on {}".format(opened.isoformat())]
    return Measured((ctx.as_of - opened).days, details=OrderedDict([("account_open_date", opened.isoformat())]),
                    lines=lines)


def tag_state(ctx, leaf):
    state = ctx.tag_states[leaf["tag"]]
    if state is None:
        return Measured(None, missing=ctx.tag_missing.get(leaf["tag"], []))
    return Measured(state)


def recurring(ctx, leaf):
    """Number of recurring streams: counterparties that appear regularly
    (every period_months months, at most max_missed periods missed), in at
    least min_occurrences months, recently, with the average payment in each
    month within amount_tolerance of the median (or within amount_floor in
    currency units, whichever is wider). Averaging per payment keeps
    a month with an extra weekly payment from breaking a steady stream."""
    flt = leaf.get("filter", {})
    window = windows.resolve(leaf["window"], ctx.as_of)
    missing = filter_missing(flt, ctx.customer)
    if missing:
        return Measured(None, window, missing=missing)
    key = ctx.key(leaf["id"])
    period = int(leaf["period_months"])
    minimum = int(leaf["min_occurrences"])
    max_missed = int(leaf.get("max_missed", 0))
    tolerance = Decimal(str(leaf["amount_tolerance"]))
    floor = Decimal(str(leaf.get("amount_floor", 0)))
    per_cp = OrderedDict()
    for index, ym in enumerate(window.months):
        bucket = ctx.data.month_bucket(key, ym)
        if bucket is None or not bucket.streams:
            continue
        for cp, (count, total) in bucket.streams.items():
            per_cp.setdefault(cp, []).append((index, units(total) / count))
    last_index = len(window.months) - 1
    streams = []
    for cp in sorted(per_cp):
        occurrences = per_cp[cp]
        if len(occurrences) < minimum:
            continue
        indices = [i for i, _ in occurrences]
        missed = 0
        regular = True
        for a, b in zip(indices, indices[1:]):
            gap = b - a
            if gap % period != 0:
                regular = False
                break
            missed += gap // period - 1
        if not regular or missed > max_missed:
            continue
        if indices[-1] < last_index - period + 1:
            continue  # the stream has stopped
        amounts = [amount for _, amount in occurrences]
        median = _median(amounts)
        allowed = max(tolerance * median, floor)
        if median <= 0 or any(abs(a - median) > allowed for a in amounts):
            continue
        streams.append((cp, len(occurrences), median))
    lines = ["{}: {} of {} months, about {:,.2f} {} each time".format(
        cp, count, len(window.months), median, ctx.taxonomy.base_currency) for cp, count, median in streams]
    return Measured(len(streams), window, OrderedDict([("streams", [s[0] for s in streams])]), lines=lines)


def days_since_last(ctx, leaf):
    flt = leaf.get("filter", {})
    window = windows.resolve(leaf["window"], ctx.as_of)
    missing = filter_missing(flt, ctx.customer)
    if missing:
        return Measured(None, window, missing=missing)
    agg = ctx.data.range_agg(ctx.key(leaf["id"]), window.start, window.end)
    if agg.last_day is None:
        return Measured(window.size, window, OrderedDict([("last_day", None)]),
                        lines=["none in the last {} days".format(window.size)])
    days = (ctx.as_of - agg.last_day).days
    return Measured(days, window, OrderedDict([("last_day", agg.last_day.isoformat())]),
                    lines=["last one on {}".format(agg.last_day.isoformat())])


def balance(ctx, leaf):
    window = windows.resolve(leaf["window"], ctx.as_of)
    if not ctx.has_balance():
        return Measured(None, window, missing=["transactions.balance_after"])
    measure = leaf["measure"]
    if window.months is None:
        months = []
        year, month = window.start.year, window.start.month
        while (year, month) <= (window.end.year, window.end.month):
            months.append((year, month))
            year, month = (year, month + 1) if month < 12 else (year + 1, 1)
    else:
        months = list(window.months)
    carried = _balance_before(ctx, months[0])
    lows, closes = [], []
    for ym in months:
        first = datetime.date(ym[0], ym[1], 1)
        whole = window.start <= first and windows.month_bounds(ym)[1] <= window.end
        if whole:
            lowest, closing = _month_balance(ctx, ym, carried)
        else:
            rows = [t for t in ctx.data.rows_by_month.get(ym, ())
                    if window.start <= t.posted_date <= window.end and t.balance_cents is not None]
            rows_before = [t for t in ctx.data.rows_by_month.get(ym, ())
                           if t.posted_date < window.start and t.balance_cents is not None]
            if rows_before:
                carried = max(rows_before, key=lambda t: t.sort_key()).balance_cents
            if rows:
                lowest = min([t.balance_cents for t in rows] + ([carried] if carried is not None else []))
                closing = max(rows, key=lambda t: t.sort_key()).balance_cents
            else:
                lowest, closing = carried, carried
        carried = closing
        if lowest is not None:
            lows.append(lowest)
        if closing is not None:
            closes.append(closing)
    if not closes:
        return Measured(None, window, note="no balance known in this window")
    if measure == "lowest":
        value = units(min(lows))
    elif measure == "latest":
        value = units(closes[-1])
    else:  # average_month_end
        value = units(sum(closes)) / Decimal(len(closes))
    return Measured(value, window, OrderedDict([("months_with_balance", len(closes))]))


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
    if metric == "recurring":
        return recurring(ctx, leaf)
    if metric == "days_since_last":
        return days_since_last(ctx, leaf)
    if metric == "balance":
        return balance(ctx, leaf)
    raise ValueError(metric)  # pragma: no cover

"""Write customer profiles into the store.

The batch rebuild and the incremental follower (engine.incremental) both
build a customer's rows with these functions, so they are always produced
the same way:

    customers        the attributes in force at the as-of date, the closing
                     date and the data notes
    feature_buckets  per feature and calendar month, recomputed from the
                     month's ledger rows, never patched
    tag_state        held, suppressed and not-evaluated tags at the as-of date
    checkpoint_tags  the tags held at each month-end checkpoint
    tag_history      entered and exited events between checkpoints

Retention: the store keeps history_months + lifecycle_months calendar months
back from the as-of month. history_months covers the longest rule window;
the extra lifecycle_months let the oldest month-end checkpoint see a full
window too, so the store's history equals a batch run's.
"""

import json
from collections import Counter, OrderedDict

from . import aggregate
from . import lifecycle as lifecycle_module
from . import windows
from .data import Customer, Transaction, parse_date
from .evaluate import evaluate_data


def retention_start(as_of, taxonomy):
    """The first day the store keeps."""
    months = taxonomy.history_months + taxonomy.lifecycle_months
    year, month = windows.shift_month((as_of.year, as_of.month), -months)
    return windows.month_bounds((year, month))[0]


def _json(value):
    return json.dumps(value, sort_keys=False, separators=(",", ":"), ensure_ascii=False)


def month_label(year_month):
    return "{:04d}-{:02d}".format(*year_month)


# -- rows <-> objects -----------------------------------------------------------

LEDGER_COLUMNS = ("customer_id", "txn_id", "posted_date", "direction", "amount_cents", "currency", "channel",
                  "category", "category_source", "counterparty", "counterparty_kind", "txn_country", "mcc",
                  "balance_cents")


def ledger_row(txn):
    return (txn.customer_id, txn.txn_id, txn.posted_date.isoformat(), txn.direction, txn.amount_cents,
            txn.currency, txn.channel, txn.category, txn.category_source, txn.counterparty,
            txn.counterparty_kind, txn.txn_country, txn.mcc, txn.balance_cents)


def transaction_from_row(row):
    (customer_id, txn_id, posted, direction, amount, currency, channel, category, source, counterparty, kind,
     country, mcc, balance) = row
    return Transaction(txn_id, customer_id, parse_date(posted), direction, amount, currency, channel, category,
                       counterparty, kind, country, mcc, balance, source)


def load_transactions(connection, customer_id):
    rows = connection.execute("SELECT {} FROM ledger WHERE customer_id = ?".format(", ".join(LEDGER_COLUMNS)),
                              (customer_id,))
    return sorted((transaction_from_row(r) for r in rows), key=Transaction.sort_key)


def load_versions(connection, customer_id, base_currency):
    """[(effective_from date, Customer)] in date order."""
    versions = []
    for effective, opened, country, currency in connection.execute(
            "SELECT effective_from, account_open_date, home_country, home_currency FROM customer_versions "
            "WHERE customer_id = ? ORDER BY effective_from", (customer_id,)):
        versions.append((parse_date(effective), Customer(customer_id, parse_date(opened or ""), country or None,
                                                          currency or base_currency)))
    return versions


def load_closed_on(connection, customer_id):
    row = connection.execute("SELECT closed_on FROM closures WHERE customer_id = ?", (customer_id,)).fetchone()
    return parse_date(row[0]) if row else None


def load_buckets(connection, customer_id, skip_months=()):
    """{(year, month): {feature key: Agg}} from the store, leaving out skip_months."""
    buckets = {}
    for key, month, n, total, mx, credit, debit, last, extra in connection.execute(
            "SELECT feature_key, month, n, total, max, credit, debit, last_day, extra FROM feature_buckets "
            "WHERE customer_id = ?", (customer_id,)):
        ym = (int(month[:4]), int(month[5:7]))
        if ym in skip_months:
            continue
        record = {"n": n, "total": total, "max": mx, "credit": credit, "debit": debit, "last_day": last,
                  "extra": extra}
        buckets.setdefault(ym, {})[key] = aggregate.Agg.from_record(record)
    return buckets


def customer_data(taxonomy, customer_id, versions, closed_on, txns, buckets=None):
    """CustomerData for evaluation, with versioned attributes and closure.
    Before a customer's first version, attributes are unknown (base currency)."""
    unknown = Customer(customer_id, None, None, taxonomy.base_currency)
    data = aggregate.CustomerData.from_rows(unknown, txns, taxonomy.specs, versions=versions or None,
                                            closed_on=closed_on)
    if buckets is not None:
        months = set(data.rows_by_month)
        for ym in months:
            buckets.setdefault(ym, {})  # a month with rows but no matching feature has no bucket rows
        data.buckets = buckets
    return data


# -- writing --------------------------------------------------------------------

def write_buckets(connection, customer_id, data, months):
    """Replace the buckets of the given (year, month)s, recomputed from rows."""
    rows = []
    for ym in sorted(months):
        connection.execute("DELETE FROM feature_buckets WHERE customer_id = ? AND month = ?",
                           (customer_id, month_label(ym)))
        data.buckets.pop(ym, None)
        for key in data.specs:
            agg = data.month_bucket(key, ym)
            if agg is None or not agg.n:
                continue
            record = agg.to_record()
            rows.append((customer_id, key, month_label(ym), record["n"], record["total"], record["max"],
                         record["credit"], record["debit"], record["last_day"], record["extra"]))
    connection.executemany(
        "INSERT INTO feature_buckets (customer_id, feature_key, month, n, total, max, credit, debit, last_day, "
        "extra) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)


def stored_checkpoints(connection, customer_id, taxonomy):
    """{checkpoint date: {tag_id: held}} from checkpoint_tags."""
    states = OrderedDict()
    for day, tags in connection.execute(
            "SELECT checkpoint, tags FROM checkpoint_tags WHERE customer_id = ? ORDER BY checkpoint", (customer_id,)):
        held = set(json.loads(tags))
        states[parse_date(day)] = OrderedDict((t["id"], t["id"] in held) for t in taxonomy.tags)
    return states


def evaluate_customer(taxonomy, data, as_of, stored, affected):
    """Evaluate the as-of date and the month-end checkpoints. A checkpoint is
    taken from stored ({date: {tag: held}}) unless it is in affected or not
    stored. Returns (current, states, lifecycle)."""
    current = evaluate_data(taxonomy, data, as_of, "held")
    states = OrderedDict()
    for day in lifecycle_module.checkpoints(as_of, taxonomy.lifecycle_months):
        if day in stored and day not in affected:
            states[day] = stored[day]
        elif day == as_of:
            states[day] = OrderedDict((tag_id, r.state is True) for tag_id, r in current.items())
        else:
            results = evaluate_data(taxonomy, data, day, with_evidence=False)
            states[day] = OrderedDict((tag_id, r.state is True) for tag_id, r in results.items())
    return current, states, lifecycle_module.lifecycle(states, current)


def write_state(connection, customer_id, as_of, current, states, life):
    """Replace the customer's tag_state, checkpoint_tags and tag_history."""
    for table in ("tag_state", "checkpoint_tags", "tag_history"):
        connection.execute("DELETE FROM {} WHERE customer_id = ?".format(table), (customer_id,))
    rows = []
    for tag_id, result in current.items():
        if result.state is True:
            entered = life.entered_on.get(tag_id)
            rows.append((customer_id, tag_id, "held", as_of.isoformat(), entered.isoformat() if entered else None,
                         1 if life.new_this_month.get(tag_id) else 0,
                         1 if life.since_window_start.get(tag_id) else 0, None, result.reason, result.rule,
                         _json(result.evidence), _json(result.facts), _json([])))
        elif result.suppressed_by:
            rows.append((customer_id, tag_id, "suppressed", as_of.isoformat(), None, 0, 0, result.suppressed_by,
                         None, None, None, None, _json([])))
        elif result.state is None:
            rows.append((customer_id, tag_id, "not_evaluated", as_of.isoformat(), None, 0, 0, None, None, None,
                         None, None, _json(result.missing)))
    connection.executemany(
        "INSERT INTO tag_state (customer_id, tag_id, status, as_of, entered_on, new_this_month, "
        "since_window_start, suppressed_by, reason, rule, evidence, facts, missing) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    connection.executemany(
        "INSERT INTO checkpoint_tags (customer_id, checkpoint, tags) VALUES (?, ?, ?)",
        [(customer_id, day.isoformat(), _json(sorted(t for t, h in held.items() if h)))
         for day, held in states.items()])
    connection.executemany(
        "INSERT INTO tag_history (customer_id, checkpoint, tag_id, event, at_window_start) VALUES (?, ?, ?, ?, ?)",
        [(customer_id, day.isoformat(), tag_id, event, 1 if at_start else 0)
         for day, tag_id, event, at_start in life.events])
    return sum(1 for r in current.values() if r.state is True)


def clear_state(connection, customer_id):
    for table in ("tag_state", "checkpoint_tags", "tag_history"):
        connection.execute("DELETE FROM {} WHERE customer_id = ?".format(table), (customer_id,))


def notes_for(connection, customer_id, as_of):
    """Data notes computed from the store, so they never depend on the order
    events arrived in."""
    used = pending = 0
    for (posted,) in connection.execute("SELECT posted_date FROM ledger WHERE customer_id = ?", (customer_id,)):
        if as_of is not None and posted <= as_of.isoformat():
            used += 1
        else:
            pending += 1
    rejected = Counter(reason for (reason,) in connection.execute(
        "SELECT reason FROM rejected_events WHERE customer_id = ?", (customer_id,)))
    return OrderedDict([("transactions_used", used), ("pending", pending),
                        ("rejected", OrderedDict(sorted(rejected.items())))])


def write_customer_row(connection, taxonomy, customer_id, as_of, versions, closed_on):
    if versions:
        if as_of is None:
            customer = versions[-1][1]
        else:
            usable = [c for day, c in versions if day <= as_of]
            customer = usable[-1] if usable else Customer(customer_id, None, None, taxonomy.base_currency)
    else:
        customer = Customer(customer_id, None, None, taxonomy.base_currency)
    notes = notes_for(connection, customer_id, as_of)
    connection.execute(
        "INSERT OR REPLACE INTO customers (customer_id, account_open_date, home_country, home_currency, notes, "
        "closed_on) VALUES (?, ?, ?, ?, ?, ?)",
        (customer_id, customer.account_open_date.isoformat() if customer.account_open_date else None,
         customer.home_country, customer.home_currency, _json(notes), closed_on.isoformat() if closed_on else None))


def write_features(connection, taxonomy):
    connection.execute("DELETE FROM features")
    connection.executemany(
        "INSERT INTO features (feature_key, definition) VALUES (?, ?)",
        [(key, aggregate.canonical_json(spec.definition())) for key, spec in taxonomy.specs.items()])


def write_meta(connection, values):
    connection.executemany("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                           [(k, "" if v is None else str(v)) for k, v in OrderedDict(values).items()])

"""Write one customer's profile into the store.

The batch rebuild and the incremental updates (phase 4) both call
write_customer(), so a customer's rows are always produced the same way:

    customers        the attributes rules read and the data notes
    ledger           the normalised transactions inside the retention window
    feature_buckets  recomputed from those ledger rows, never patched
    tag_state        held, suppressed and not-evaluated tags at the as-of date
    checkpoint_tags  the tags held at each month-end checkpoint
    tag_history      entered and exited events between checkpoints

Retention: the store keeps history_months + lifecycle_months calendar months
back from the as-of month. history_months covers the longest rule window;
the extra lifecycle_months let the oldest month-end checkpoint see a full
window too, so the store's history equals a batch run's.
"""

import json
from collections import OrderedDict

from . import aggregate
from . import lifecycle as lifecycle_module
from . import windows
from .evaluate import evaluate_data


def retention_start(as_of, taxonomy):
    """The first day the store keeps."""
    months = taxonomy.history_months + taxonomy.lifecycle_months
    year, month = windows.shift_month((as_of.year, as_of.month), -months)
    return windows.month_bounds((year, month))[0]


def _json(value):
    return json.dumps(value, sort_keys=False, separators=(",", ":"), ensure_ascii=False)


def ledger_row(txn):
    return (txn.customer_id, txn.txn_id, txn.posted_date.isoformat(), txn.direction, txn.amount_cents,
            txn.currency, txn.channel, txn.category, txn.category_source, txn.counterparty,
            txn.counterparty_kind, txn.txn_country, txn.mcc, txn.balance_cents)


def delete_customer(connection, customer_id):
    for table in ("customers", "ledger", "feature_buckets", "tag_state", "checkpoint_tags", "tag_history"):
        connection.execute("DELETE FROM {} WHERE customer_id = ?".format(table), (customer_id,))


def write_customer(connection, taxonomy, customer, txns, as_of, notes, customer_for=None):
    """Replace every row of one customer. txns are the customer's usable
    transactions (any order); rows before the retention window or after the
    as-of date are not kept. Returns the number of held tags."""
    start = retention_start(as_of, taxonomy)
    kept = sorted((t for t in txns if start <= t.posted_date <= as_of), key=lambda t: t.sort_key())
    delete_customer(connection, customer.customer_id)
    connection.execute(
        "INSERT INTO customers (customer_id, account_open_date, home_country, home_currency, notes) "
        "VALUES (?, ?, ?, ?, ?)",
        (customer.customer_id, customer.account_open_date.isoformat() if customer.account_open_date else None,
         customer.home_country, customer.home_currency, _json(notes)))
    connection.executemany(
        "INSERT INTO ledger (customer_id, txn_id, posted_date, direction, amount_cents, currency, channel, "
        "category, category_source, counterparty, counterparty_kind, txn_country, mcc, balance_cents) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [ledger_row(t) for t in kept])

    data = aggregate.CustomerData.from_rows(customer, kept, taxonomy.specs, customer_for=customer_for)
    bucket_rows = []
    for (ym, key), agg in data.all_buckets().items():
        record = agg.to_record()
        bucket_rows.append((customer.customer_id, key, "{:04d}-{:02d}".format(*ym), record["n"], record["total"],
                            record["max"], record["credit"], record["debit"], record["last_day"], record["extra"]))
    connection.executemany(
        "INSERT INTO feature_buckets (customer_id, feature_key, month, n, total, max, credit, debit, last_day, "
        "extra) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", bucket_rows)

    current = evaluate_data(taxonomy, data, as_of, "held")
    states = lifecycle_module.checkpoint_states(taxonomy, data, as_of, taxonomy.lifecycle_months, current)
    life = lifecycle_module.lifecycle(states, current)
    held = write_tags(connection, customer.customer_id, as_of, current, life)
    connection.executemany(
        "INSERT INTO checkpoint_tags (customer_id, checkpoint, tags) VALUES (?, ?, ?)",
        [(customer.customer_id, day.isoformat(), _json(sorted(t for t, h in tags.items() if h)))
         for day, tags in states.items()])
    connection.executemany(
        "INSERT INTO tag_history (customer_id, checkpoint, tag_id, event, at_window_start) VALUES (?, ?, ?, ?, ?)",
        [(customer.customer_id, day.isoformat(), tag_id, event, 1 if at_start else 0)
         for day, tag_id, event, at_start in life.events])
    return held


def write_tags(connection, customer_id, as_of, current, life):
    rows = []
    held = 0
    for tag_id, result in current.items():
        if result.state is True:
            held += 1
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
    return held


def write_features(connection, taxonomy):
    connection.execute("DELETE FROM features")
    connection.executemany(
        "INSERT INTO features (feature_key, definition) VALUES (?, ?)",
        [(key, aggregate.canonical_json(spec.definition())) for key, spec in taxonomy.specs.items()])


def write_meta(connection, values):
    connection.executemany("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                           [(k, str(v)) for k, v in OrderedDict(values).items()])

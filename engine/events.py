"""The event model: versioned JSON events, the only input of the builder.

Envelope (schema "customer-tagging.event/1"; every key required unless noted):

    {"schema": "customer-tagging.event/1", "id": "...", "type": "...",
     "time": "YYYY-MM-DD", "version": 0, "customer_id": "...", "data": {...}}

    id          unique; an id seen before is skipped, and the same id with
                different content is refused
    time        the date the event takes effect (for a posting, the posted date)
    version     the source's change sequence for the thing the event is about
                (a log position or an outbox id); a higher version wins
    customer_id absent only for clock.tick

Types and their data:

    transaction.posted     the transaction's columns as strings: txn_id,
                           amount, currency, direction, channel, category,
                           counterparty, txn_country, mcc, balance_after and
                           balance_currency (needed with balance_after). The
                           posted date is the event's time.
    transaction.corrected  a full after-image: the same keys plus posted_date.
                           Never a difference.
    transaction.reversed   {"txn_id": ...}: the transaction no longer counts.
    customer.updated       a full after-image of the attributes rules read:
                           account_open_date, home_country, home_currency.
                           It takes effect from the event's time. With
                           profiling_opt_out set (see policy.opted_out) it is
                           an objection to profiling: the store forgets the
                           customer and drops their later events, whatever
                           the event's date; nothing else is needed.
    account.closed         {}: the customer has no tags from the event's time.
    clock.tick             {}: the day given by time is complete; the store's
                           as-of date moves to it. An older tick changes nothing.

How a bank's change data capture maps onto it: an insert into the posted
transactions table is transaction.posted; an update of a transaction row is
transaction.corrected carrying the whole new row; a reversal record (or a
delete) is transaction.reversed; an insert or update in the customer table is
customer.updated with the whole row; a closure is account.closed; and the end
of each business day is clock.tick. The log position (or outbox id) is the
version, and the change's own id is the event id. A bank-side bridge writes
these events to a JSONL file or a SQLite outbox table (engine/feeds.py); the
plugin depends on no message broker.
"""

import datetime
import hashlib
import json
from collections import OrderedDict

from . import data as data_module
from . import policy

SCHEMA = "customer-tagging.event/1"
TYPES = ("transaction.posted", "transaction.corrected", "transaction.reversed", "customer.updated",
         "account.closed", "clock.tick")
ENVELOPE_KEYS = {"schema", "id", "type", "time", "version", "customer_id", "data"}
TXN_KEYS = ("txn_id", "amount", "currency", "direction", "channel", "category", "counterparty", "txn_country",
            "mcc", "balance_after", "balance_currency")
CUSTOMER_KEYS = ("account_open_date", "home_country", "home_currency")
DATA_KEYS = {
    "transaction.posted": set(TXN_KEYS),
    "transaction.corrected": set(TXN_KEYS) | {"posted_date"},
    "transaction.reversed": {"txn_id"},
    "customer.updated": set(CUSTOMER_KEYS) | {"profiling_opt_out"},
    "account.closed": set(),
    "clock.tick": set(),
}
REQUIRED_DATA = {
    "transaction.posted": {"txn_id", "amount", "currency"},
    "transaction.corrected": {"txn_id", "amount", "currency", "posted_date"},
    "transaction.reversed": {"txn_id"},
    "customer.updated": {"home_currency"},
    "account.closed": set(),
    "clock.tick": set(),
}
MAX_EVENT_BYTES = 16384
EPOCH = "1900-01-01"  # effective date of attributes loaded from a customers file


class EventError(ValueError):
    """An event that cannot be used. reason is a short stable code."""

    def __init__(self, reason, detail=""):
        ValueError.__init__(self, "{}: {}".format(reason, detail) if detail else reason)
        self.reason = reason


class Event(object):
    __slots__ = ("id", "type", "day", "version", "customer_id", "data", "digest", "raw")

    def __init__(self, id, type, day, version, customer_id, data, digest, raw):
        self.id = id
        self.type = type
        self.day = day  # the event's "time" field: the date it takes effect
        self.version = version
        self.customer_id = customer_id
        self.data = data
        self.digest = digest
        self.raw = raw

    def as_dict(self):
        return self.raw


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest_of(raw):
    return "sha256:" + hashlib.sha256(canonical(raw).encode("utf-8")).hexdigest()


def _date(text, reason):
    if not isinstance(text, str):
        raise EventError(reason)
    try:
        return datetime.datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise EventError(reason, text)


def parse(raw):
    """Validate one event (a dict, or a JSON text) and return an Event.

    Only the envelope is checked here; a transaction's amount, currency and so
    on are checked when it is applied, and a bad one is recorded as rejected."""
    if isinstance(raw, (bytes, str)):
        if len(raw) > MAX_EVENT_BYTES:
            raise EventError("too_large")
        try:
            raw = json.loads(raw, object_pairs_hook=OrderedDict)
        except ValueError as exc:
            raise EventError("not_json", str(exc))
    if not isinstance(raw, dict):
        raise EventError("not_an_object")
    unknown = sorted(set(raw) - ENVELOPE_KEYS)
    if unknown:
        raise EventError("unknown_keys", ", ".join(unknown))
    if raw.get("schema") != SCHEMA:
        raise EventError("unknown_schema", str(raw.get("schema")))
    event_id = raw.get("id")
    if not isinstance(event_id, str) or not 0 < len(event_id) <= 200:
        raise EventError("bad_id")
    kind = raw.get("type")
    if kind not in TYPES:
        raise EventError("unknown_type", str(kind))
    time = _date(raw.get("time"), "bad_time")
    version = raw.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        raise EventError("bad_version")
    customer_id = raw.get("customer_id")
    if kind == "clock.tick":
        if customer_id is not None:
            raise EventError("tick_has_customer")
    elif not isinstance(customer_id, str) or not 0 < len(customer_id) <= 100:
        raise EventError("bad_customer_id")
    payload = raw.get("data")
    if not isinstance(payload, dict):
        raise EventError("bad_data")
    unknown = sorted(set(payload) - DATA_KEYS[kind])
    if unknown:
        raise EventError("unknown_data_keys", ", ".join(unknown))
    missing = sorted(REQUIRED_DATA[kind] - set(payload))
    if missing and not (kind == "customer.updated" and policy.opted_out(payload.get("profiling_opt_out"))):
        raise EventError("missing_data_keys", ", ".join(missing))
    for key, value in payload.items():
        if value is not None and not isinstance(value, str):
            raise EventError("data_values_are_strings", key)
    return Event(event_id, kind, time, version, customer_id, payload, digest_of(raw), raw)


def make(event_id, kind, time, customer_id=None, data=None, version=0):
    """Build a valid event dict (used by the CSV converter and tests)."""
    raw = OrderedDict([("schema", SCHEMA), ("id", event_id), ("type", kind),
                       ("time", time if isinstance(time, str) else time.isoformat()), ("version", version)])
    if customer_id is not None:
        raw["customer_id"] = customer_id
    raw["data"] = OrderedDict(sorted((data or {}).items()))
    return raw


def transaction_of(event, taxonomy, posted_date=None):
    """Normalise a posting or correction into a Transaction, or raise EventError.

    Normalisation depends only on the event and the taxonomy (never on the
    customer's current attributes), so it gives the same result whatever
    order events arrive in."""
    payload = event.data
    posted = posted_date or (event.day if event.type == "transaction.posted"
                             else _date(payload.get("posted_date"), "bad_posted_date"))
    currency = (payload.get("currency") or "").upper()
    if not currency:
        raise EventError("missing_currency")
    balance_currency = (payload.get("balance_currency") or "").upper() or None
    if payload.get("balance_after") and not balance_currency:
        raise EventError("missing_balance_currency")
    row = {key: payload.get(key) or "" for key in TXN_KEYS}
    row["posted_date"] = posted.isoformat()
    holder = data_module.Customer(event.customer_id, None, None, balance_currency or currency)
    txn, reason, _ = data_module.normalise_transaction(row, holder, taxonomy)
    if txn is None:
        raise EventError(reason)
    if not txn.txn_id:
        raise EventError("missing_txn_id")
    return txn


def is_opt_out(event):
    """Is this event a customer's objection to profiling?"""
    return event.type == "customer.updated" and policy.opted_out(event.data.get("profiling_opt_out"))


def customer_of(event, base_currency):
    """The attributes in a customer.updated event, as a Customer."""
    row = {"customer_id": event.customer_id}
    row.update({key: event.data.get(key) or "" for key in CUSTOMER_KEYS})
    customer, problem = data_module.customer_from_row(row, base_currency)
    if problem:
        raise EventError(problem)
    return customer


# -- the CSV copy as events ----------------------------------------------------

def csv_events(customers_path, transactions_path, taxonomy, as_of=None, sink=None):
    """Turn the read-only CSV copy into events, one at a time, keeping stage
    1's file rules: rows for unknown customers are left out, an empty currency
    is the customer's home currency, a row without a txn_id gets a stable id
    from its line, and the first of two rows with the same txn_id wins (the
    lower line number is the lower event id).

    Yields customer.updated for every customer, transaction.posted for every
    row, and last one clock.tick for the as-of date: when as_of is None, the
    latest posted date of a usable transaction, never today. sink, a dict,
    receives "rejected" (rows that cannot become events at all:
    [(event_id, customer_id, reason)]) and "notes" (file-level notes)."""
    sink = sink if sink is not None else {}
    sink.setdefault("rejected", [])
    customers, customer_notes = data_module.load_customers(customers_path, taxonomy.base_currency,
                                                           keep_opted_out=True)
    ignored = []
    for cid, customer in customers.items():
        if customer.opted_out:  # only the objection: none of their attributes
            yield make("csv-customer-" + cid, "customer.updated", EPOCH, cid, {"profiling_opt_out": "true"})
            continue
        yield make("csv-customer-" + cid, "customer.updated", EPOCH, cid, OrderedDict([
            ("account_open_date", customer.account_open_date.isoformat() if customer.account_open_date else ""),
            ("home_country", customer.home_country or ""),
            ("home_currency", customer.home_currency),
        ]))
    skipped = OrderedDict()
    latest = None
    rows_read = 0
    rows = data_module.iter_rows(transactions_path, data_module.policy.TRANSACTION_COLUMNS,
                                 ("customer_id", "posted_date", "amount"), ignored)
    for line, row in enumerate(rows, start=2):
        rows_read += 1
        cid = row.get("customer_id", "")
        customer = customers.get(cid)
        if customer is None or customer.opted_out:
            reason = "opted_out" if customer is not None else "unknown_customer"
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        event_id = "csv-line-{:07d}".format(line)
        posted = data_module.parse_date(row.get("posted_date", ""))
        if posted is None:
            sink["rejected"].append((event_id, cid, "bad_or_missing_date"))
            continue
        payload = OrderedDict((key, row.get(key, "") or "") for key in TXN_KEYS[:-1])
        payload["txn_id"] = payload["txn_id"] or "line-{:07d}".format(line)
        payload["currency"] = payload["currency"] or customer.home_currency
        payload["balance_currency"] = customer.home_currency if payload.get("balance_after") else ""
        yield make(event_id, "transaction.posted", posted, cid, payload)
        amount = data_module._parse_amount(payload["amount"])
        if amount is not None and amount != 0 and payload["currency"].upper() in taxonomy.fx_rates and \
                (latest is None or posted > latest):
            latest = posted
    if as_of is None:
        if latest is None:
            raise data_module.DataError("no usable transactions: pass an explicit as-of date")
        as_of = latest
    yield make("csv-as-of-" + as_of.isoformat(), "clock.tick", as_of)
    sink.setdefault("notes", OrderedDict()).update([
        ("customers", customer_notes),
        ("transactions", OrderedDict([("rows_read", rows_read), ("skipped", skipped), ("ignored_columns", ignored)]))])


def events_from_csv(customers_path, transactions_path, taxonomy, as_of=None):
    """csv_events() as a list: returns (events, rejected, notes)."""
    sink = {}
    events = list(csv_events(customers_path, transactions_path, taxonomy, as_of, sink))
    return events, sink["rejected"], sink["notes"]

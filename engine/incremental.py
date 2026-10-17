"""Continuous updates, and the batch rebuild they must always equal.

Two ways to produce a profile store from a set of events:

    rebuild_from_events()  the batch path: resolve the whole set at once
    Follower.apply()       the incremental path: apply events as they arrive

Both resolve every table as a function of the *set* of accepted events, so
for any arrival order within the allowed lateness the two stores are equal
(tests/test_incremental.py checks this over many seeded orders):

* Duplicates are skipped by event id; the same id with different content is
  refused.
* Each transaction id is a register. The winning image has the highest
  version; at equal versions a reversal beats a posting; then the lowest
  event id wins. A posting, a correction and a reversal are all full images,
  so a later arrival can never be a difference applied to the wrong base.
* Customer attributes are versioned by effective date, each version won by
  the highest version and then the lowest event id. A closure takes the
  earliest closing date.
* The as-of date is the latest clock.tick. Retention prunes by the same rule
  whatever the order, because its start only moves forward.
* Buckets are recomputed for the affected months from the ledger; tags are
  re-evaluated for the affected customer at the as-of date and at every
  checkpoint the event can change. A new customer gets every retained
  checkpoint. A month-end tick adds a checkpoint for every customer.

Allowed lateness: a month is sealed once its last day is at least
allowed_lateness_days before the as-of date. An event whose effective date
falls in a sealed month is late: it is kept in late_events, counted, and not
applied, so sealed history never changes; a deliberate rebuild folds it in.
"""

import datetime
import os
from collections import OrderedDict

from . import ENGINE_VERSION, DataError, load_taxonomy, DEFAULT_TAXONOMY
from . import events as events_module
from . import lifecycle as lifecycle_module
from . import profile
from . import store as store_module
from . import windows
from .data import Customer, parse_date
from .events import EventError

RANK = {"posted": 0, "reversed": 1}
DEFAULT_LATENESS_DAYS = 3

# Tables the invariant compares; runs, late_events and feed_checkpoints record
# what happened when, so they are not part of the profile.
STATE_TABLES = ("meta", "schema_migrations", "customers", "customer_versions", "closures", "txn_registers",
                "ledger", "features", "feature_buckets", "tag_state", "checkpoint_tags", "tag_history",
                "events_seen", "rejected_events")


def beats(a, b):
    """Does image key a = (version, status, event_id) win over b?"""
    if a[0] != b[0]:
        return a[0] > b[0]
    if RANK[a[1]] != RANK[b[1]]:
        return RANK[a[1]] > RANK[b[1]]
    return a[2] < b[2]


def version_beats(a, b):
    """Does attribute version a = (version, event_id) win over b?"""
    if a[0] != b[0]:
        return a[0] > b[0]
    return a[1] < b[1]


def sealed_end(as_of, lateness_days):
    """The last day of the latest sealed month, or None."""
    if as_of is None:
        return None
    cut = as_of - datetime.timedelta(days=lateness_days)
    return windows.month_bounds(windows.last_complete_month(cut))[1]


def _iso(day):
    return day.isoformat() if day is not None else None


def _month(day):
    return (day.year, day.month)


def _meta_values(taxonomy, as_of, lateness_days, state):
    return [
        ("state", state),
        ("engine_version", ENGINE_VERSION),
        ("taxonomy_version", taxonomy.version),
        ("taxonomy_hash", taxonomy.content_hash),
        ("base_currency", taxonomy.base_currency),
        ("as_of", _iso(as_of) or ""),
        ("history_months", taxonomy.history_months),
        ("lifecycle_months", taxonomy.lifecycle_months),
        ("retention_start", _iso(profile.retention_start(as_of, taxonomy)) if as_of else ""),
        ("allowed_lateness_days", lateness_days),
    ]


def _invalid_id(raw):
    if isinstance(raw, dict) and isinstance(raw.get("id"), str) and raw.get("id"):
        return raw["id"]
    text = raw if isinstance(raw, (str, bytes)) else events_module.canonical(raw)
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    import hashlib
    return "invalid-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# -- the batch path -----------------------------------------------------------------

STAGING = """
CREATE TEMP TABLE stage_events (event_id TEXT, digest TEXT, type TEXT, customer_id TEXT, time TEXT);
CREATE TEMP TABLE stage_images (customer_id TEXT, txn_id TEXT, version INTEGER, rank INTEGER, event_id TEXT,
    posted_date TEXT, direction TEXT, amount_cents INTEGER, currency TEXT, channel TEXT, category TEXT,
    category_source TEXT, counterparty TEXT, counterparty_kind TEXT, txn_country TEXT, mcc TEXT,
    balance_cents INTEGER);
CREATE TEMP TABLE stage_versions (customer_id TEXT, effective_from TEXT, version INTEGER, event_id TEXT,
    account_open_date TEXT, home_country TEXT, home_currency TEXT);
CREATE TEMP TABLE stage_closures (customer_id TEXT, closed_on TEXT)
"""
_CHUNK = 5000


def rebuild_from_events(raw_events, store_path, taxonomy=None, as_of=None, pre_rejected=(),
                        lateness_days=DEFAULT_LATENESS_DAYS, notes=None, snapshot="", clock=None):
    """Build a complete store from a set of events. Returns a summary dict.

    raw_events may be any iterable (it is read once). Events are staged in
    temporary tables and every register, attribute version and closure is
    resolved in SQL by the same order the follower uses, so memory does not
    grow with the number of transactions. The store is written to a temporary
    file and renamed into place only when complete. pre_rejected lists input
    rows that could not become events at all [(event_id, customer_id, reason)];
    it is read after raw_events, so a generator may fill it."""
    from .build import utc_now
    clock = clock or utc_now
    if taxonomy is None or isinstance(taxonomy, str):
        taxonomy = load_taxonomy(taxonomy or DEFAULT_TAXONOMY)
    started = clock()
    temporary = store_path + ".building"
    if os.path.exists(temporary):
        os.remove(temporary)
    connection = store_module.connect_rw(temporary)
    try:
        store_module.apply_migrations(connection)
        connection.execute("BEGIN IMMEDIATE")
        for statement in STAGING.strip().split(";"):
            connection.execute(statement)
        read, ticks = _stage(connection, raw_events, taxonomy)
        for event_id, customer_id, reason in pre_rejected:
            connection.execute("INSERT OR IGNORE INTO rejected_events (event_id, customer_id, time, reason) "
                               "VALUES (?, ?, NULL, ?)", (event_id, customer_id, reason))
        conflict = connection.execute("SELECT event_id FROM stage_events GROUP BY event_id "
                                      "HAVING COUNT(DISTINCT digest) > 1 LIMIT 1").fetchone()
        if conflict:
            raise DataError("conflicting events share the id {}".format(conflict[0]))
        if as_of is None and ticks:
            as_of = max(ticks)
        profile.write_meta(connection, _meta_values(taxonomy, as_of, lateness_days, store_module.STATE_BUILDING))
        profile.write_features(connection, taxonomy)
        _resolve(connection)
        if as_of is not None:
            prune(connection, profile.retention_start(as_of, taxonomy))
        customers = [row[0] for row in connection.execute(
            "SELECT customer_id FROM stage_images UNION SELECT customer_id FROM stage_versions "
            "UNION SELECT customer_id FROM stage_closures ORDER BY 1")]
        for table in ("stage_events", "stage_images", "stage_versions", "stage_closures"):
            connection.execute("DROP TABLE {}".format(table))
        held = 0
        for cid in customers:
            held += _write_customer(connection, taxonomy, cid, as_of, months=None, affected=None)
        txn_count = connection.execute("SELECT COUNT(*) FROM ledger").fetchone()[0]
        applied = connection.execute("SELECT COUNT(*) FROM events_seen").fetchone()[0]
        rejected = connection.execute("SELECT COUNT(*) FROM rejected_events").fetchone()[0]
        connection.execute(
            "INSERT INTO runs (kind, as_of, engine_version, taxonomy_version, taxonomy_hash, input_snapshot_hash, "
            "customers, transactions, tags_held, notes, started_at, finished_at, events_read, events_applied, "
            "events_rejected) VALUES ('rebuild', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (_iso(as_of) or "", ENGINE_VERSION, taxonomy.version, taxonomy.content_hash, snapshot, len(customers),
             txn_count, held, store_module.canonical(notes or {}), started, clock(), read, applied, rejected))
        profile.write_meta(connection, [("state", store_module.STATE_READY)])
        connection.execute("COMMIT")
        connection.execute("VACUUM")
    except BaseException:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        connection.close()
        if os.path.exists(temporary):
            os.remove(temporary)
        raise
    connection.close()
    os.replace(temporary, store_path)
    return {"store": store_path, "as_of": _iso(as_of) or "", "customers": len(customers), "transactions": txn_count,
            "tags_held": held, "taxonomy_version": taxonomy.version, "events": applied, "rejected": rejected}


def _stage(connection, raw_events, taxonomy):
    """Parse every event into the staging tables. Returns (events read, tick dates)."""
    buffers = {"events": [], "images": [], "versions": [], "closures": [], "rejected": []}
    sql = {
        "events": "INSERT INTO stage_events VALUES (?, ?, ?, ?, ?)",
        "images": "INSERT INTO stage_images VALUES ({})".format(", ".join("?" * 17)),
        "versions": "INSERT INTO stage_versions VALUES (?, ?, ?, ?, ?, ?, ?)",
        "closures": "INSERT INTO stage_closures VALUES (?, ?)",
        "rejected": "INSERT OR IGNORE INTO rejected_events (event_id, customer_id, time, reason) VALUES (?, ?, ?, ?)",
    }

    def flush(name):
        if buffers[name]:
            connection.executemany(sql[name], buffers[name])
            del buffers[name][:]

    read, ticks = 0, set()
    for raw in raw_events:
        read += 1
        try:
            event = events_module.parse(raw)
        except EventError as exc:
            buffers["rejected"].append((_invalid_id(raw), None, None, exc.reason))
            continue
        cid = event.customer_id
        buffers["events"].append((event.id, event.digest, event.type, cid, _iso(event.day)))
        try:
            if event.type == "clock.tick":
                ticks.add(event.day)
            elif event.type in ("transaction.posted", "transaction.corrected"):
                txn = events_module.transaction_of(event, taxonomy)
                row = profile.ledger_row(txn)
                buffers["images"].append((cid, txn.txn_id, event.version, RANK["posted"], event.id) + row[2:])
            elif event.type == "transaction.reversed":
                buffers["images"].append((cid, event.data["txn_id"], event.version, RANK["reversed"], event.id,
                                          _iso(event.day)) + (None,) * 11)
            elif event.type == "customer.updated":
                customer = events_module.customer_of(event, taxonomy.base_currency)
                buffers["versions"].append((cid, _iso(event.day), event.version, event.id,
                                            _iso(customer.account_open_date), customer.home_country,
                                            customer.home_currency))
            else:  # account.closed
                buffers["closures"].append((cid, _iso(event.day)))
        except EventError as exc:
            buffers["rejected"].append((event.id, cid, _iso(event.day), exc.reason))
        for name, rows in buffers.items():
            if len(rows) >= _CHUNK:
                flush(name)
    for name in buffers:
        flush(name)
    return read, ticks


def _resolve(connection):
    """Pick every register's, version's and closure's winner from the staged
    events, by the same order the follower uses (see beats and version_beats)."""
    connection.execute("INSERT INTO events_seen (event_id, digest, type, customer_id, time) "
                       "SELECT DISTINCT event_id, digest, type, customer_id, time FROM stage_events")
    ranked = ("SELECT *, ROW_NUMBER() OVER (PARTITION BY customer_id, txn_id "
              "ORDER BY version DESC, rank DESC, event_id ASC) AS winner FROM stage_images")
    connection.execute(
        "INSERT INTO txn_registers (customer_id, txn_id, version, status, event_id, posted_date) "
        "SELECT customer_id, txn_id, version, CASE rank WHEN 1 THEN 'reversed' ELSE 'posted' END, event_id, "
        "posted_date FROM ({}) WHERE winner = 1".format(ranked))
    connection.execute(
        "INSERT INTO ledger ({0}) SELECT {0} FROM ({1}) WHERE winner = 1 AND rank = 0".format(
            ", ".join(profile.LEDGER_COLUMNS), ranked))
    connection.execute(
        "INSERT INTO customer_versions (customer_id, effective_from, version, event_id, account_open_date, "
        "home_country, home_currency) SELECT customer_id, effective_from, version, event_id, account_open_date, "
        "home_country, home_currency FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY customer_id, effective_from "
        "ORDER BY version DESC, event_id ASC) AS winner FROM stage_versions) WHERE winner = 1")
    connection.execute("INSERT INTO closures (customer_id, closed_on) "
                       "SELECT customer_id, MIN(closed_on) FROM stage_closures GROUP BY customer_id")


def prune(connection, start):
    """Drop what retention no longer keeps. Applied after every tick by the
    follower and once by the batch rebuild: start only moves forward, so the
    result is the same."""
    first = start.isoformat()
    connection.execute("DELETE FROM ledger WHERE posted_date < ?", (first,))
    connection.execute("DELETE FROM txn_registers WHERE posted_date < ?", (first,))
    connection.execute("DELETE FROM feature_buckets WHERE month < ?", (first[:7],))
    connection.execute(
        "DELETE FROM customer_versions WHERE effective_from < ? AND effective_from < ("
        "SELECT MAX(v.effective_from) FROM customer_versions v WHERE v.customer_id = customer_versions.customer_id "
        "AND v.effective_from <= ?)", (first, first))
    connection.execute("DELETE FROM events_seen WHERE time < ?", (first,))
    connection.execute("DELETE FROM rejected_events WHERE time IS NOT NULL AND time < ?", (first,))


def _write_customer(connection, taxonomy, cid, as_of, months, affected):
    """Recompute one customer's buckets (all months when months is None) and,
    when there is an as-of date, its tags (every checkpoint when affected is
    None). Returns the number of held tags."""
    versions = profile.load_versions(connection, cid, taxonomy.base_currency)
    closed_on = profile.load_closed_on(connection, cid)
    txns = profile.load_transactions(connection, cid)
    if months is None:
        data = profile.customer_data(taxonomy, cid, versions, closed_on, txns)
        months = set(data.rows_by_month)
        connection.execute("DELETE FROM feature_buckets WHERE customer_id = ?", (cid,))
    else:
        data = profile.customer_data(taxonomy, cid, versions, closed_on, txns,
                                     profile.load_buckets(connection, cid, skip_months=months))
    profile.write_buckets(connection, cid, data, months)
    held = 0
    if as_of is not None:
        days = lifecycle_module.checkpoints(as_of, taxonomy.lifecycle_months)
        stored = profile.stored_checkpoints(connection, cid, taxonomy) if affected is not None else {}
        current, states, life = profile.evaluate_customer(
            taxonomy, data, as_of, stored, set(days) if affected is None else affected)
        held = profile.write_state(connection, cid, as_of, current, states, life)
    profile.write_customer_row(connection, taxonomy, cid, as_of, versions, closed_on)
    return held


# -- the incremental path -------------------------------------------------------------

class Follower(object):
    """Apply events to a profile store as they arrive.

    Each call to apply() is one SQLite transaction holding every effect of
    the batch and the feed position it read up to, so a crash loses nothing
    and repeats nothing."""

    def __init__(self, store_path, taxonomy=None, lateness_days=DEFAULT_LATENESS_DAYS, clock=None):
        from .build import utc_now
        self.clock = clock or utc_now
        if taxonomy is None or isinstance(taxonomy, str):
            taxonomy = load_taxonomy(taxonomy or DEFAULT_TAXONOMY)
        self.taxonomy = taxonomy
        self.lateness_days = lateness_days
        self.path = store_path
        fresh = not os.path.exists(store_path)
        self.connection = store_module.connect_rw(store_path)
        self.connection.execute("PRAGMA journal_mode = WAL")
        store_module.apply_migrations(self.connection)
        if fresh:
            self.connection.execute("BEGIN IMMEDIATE")
            profile.write_meta(self.connection, _meta_values(taxonomy, None, lateness_days, store_module.STATE_READY))
            profile.write_features(self.connection, taxonomy)
            self.connection.execute("COMMIT")
        meta = store_module.check_store(self.connection, taxonomy)
        if meta.get("allowed_lateness_days", str(lateness_days)) != str(lateness_days):
            profile.write_meta(self.connection, [("allowed_lateness_days", lateness_days)])
        self.as_of = parse_date(meta.get("as_of", ""))

    def close(self):
        if self.connection is not None:
            self.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.connection.execute("PRAGMA journal_mode = DELETE")
            self.connection.close()
            self.connection = None

    def position(self, feed):
        row = self.connection.execute("SELECT position, identity FROM feed_checkpoints WHERE feed = ?",
                                      (feed,)).fetchone()
        return (row[0], row[1]) if row else (None, None)

    # -- applying a batch -----------------------------------------------------------

    def apply(self, raw_events, feed=None, position=None, identity=None):
        """Apply a batch of events (dicts or JSON texts). Returns counts."""
        counts = OrderedDict([("read", 0), ("applied", 0), ("duplicate", 0), ("rejected", 0), ("late", 0)])
        started = self.clock()
        connection = self.connection
        connection.execute("BEGIN IMMEDIATE")
        try:
            dirty = OrderedDict()
            for raw in raw_events:
                counts["read"] += 1
                self._one(raw, dirty, counts)
            self._flush(dirty)
            if feed is not None:
                connection.execute("INSERT OR REPLACE INTO feed_checkpoints (feed, position, identity) VALUES (?, ?, ?)",
                                   (feed, str(position), identity or ""))
            held = connection.execute("SELECT COUNT(*) FROM tag_state WHERE status = 'held'").fetchone()[0]
            customers = connection.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
            txns = connection.execute("SELECT COUNT(*) FROM ledger").fetchone()[0]
            connection.execute(
                "INSERT INTO runs (kind, as_of, engine_version, taxonomy_version, taxonomy_hash, input_snapshot_hash, "
                "customers, transactions, tags_held, notes, started_at, finished_at, events_read, events_applied, "
                "events_duplicate, events_rejected, events_late) "
                "VALUES ('follow', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (_iso(self.as_of) or "", ENGINE_VERSION, self.taxonomy.version, self.taxonomy.content_hash,
                 "feed:{}@{}".format(feed, position) if feed else "", customers, txns, held,
                 store_module.canonical({"feed": feed, "position": str(position) if feed else None}),
                 started, self.clock(), counts["read"], counts["applied"], counts["duplicate"], counts["rejected"],
                 counts["late"]))
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            self.as_of = parse_date(store_module.meta(connection).get("as_of", ""))
            raise
        return counts

    def _start(self):
        return profile.retention_start(self.as_of, self.taxonomy) if self.as_of else None

    def _record_rejected(self, event_id, customer_id, day, reason):
        start = self._start()
        if day is not None and start is not None and day < start:
            return
        self.connection.execute(
            "INSERT OR IGNORE INTO rejected_events (event_id, customer_id, time, reason) VALUES (?, ?, ?, ?)",
            (event_id, customer_id, _iso(day), reason))

    def _one(self, raw, dirty, counts):
        connection = self.connection
        try:
            event = events_module.parse(raw)
        except EventError as exc:
            self._record_rejected(_invalid_id(raw), None, None, exc.reason)
            counts["rejected"] += 1
            return
        seen = connection.execute("SELECT digest FROM events_seen WHERE event_id = ?", (event.id,)).fetchone()
        if seen is not None:
            if seen[0] == event.digest:
                counts["duplicate"] += 1
            else:
                self._late(event, "conflicting_duplicate")
                counts["late"] += 1
            return
        if event.type == "clock.tick":
            self._seen(event)
            self._tick(event.day, dirty)
            counts["applied"] += 1
            return
        sealed = sealed_end(self.as_of, self.lateness_days)
        if sealed is not None and self._effective_date(event) <= sealed:
            self._late(event, "beyond_allowed_lateness")
            counts["late"] += 1
            return
        self._seen(event)
        try:
            self._apply_event(event, dirty)
        except EventError as exc:
            self._record_rejected(event.id, event.customer_id, event.day, exc.reason)
            counts["rejected"] += 1
            return
        counts["applied"] += 1

    def _seen(self, event):
        start = self._start()
        if start is not None and event.day < start:
            return
        self.connection.execute("INSERT INTO events_seen (event_id, digest, type, customer_id, time) VALUES (?, ?, ?, ?, ?)",
                                (event.id, event.digest, event.type, event.customer_id, _iso(event.day)))

    def _late(self, event, reason):
        self.connection.execute(
            "INSERT OR IGNORE INTO late_events (event_id, customer_id, event, reason, as_of) VALUES (?, ?, ?, ?, ?)",
            (event.id, event.customer_id, events_module.canonical(event.raw), reason, _iso(self.as_of) or ""))

    def _register(self, cid, txn_id):
        row = self.connection.execute(
            "SELECT version, status, event_id, posted_date FROM txn_registers WHERE customer_id = ? AND txn_id = ?",
            (cid, txn_id)).fetchone()
        return ((row[0], row[1], row[2]), parse_date(row[3])) if row else (None, None)

    def _effective_date(self, event):
        if event.type == "transaction.corrected":
            _, old = self._register(event.customer_id, event.data.get("txn_id"))
            new = parse_date(event.data.get("posted_date") or "") or event.day
            return min(d for d in (old, new) if d is not None)
        if event.type == "transaction.reversed":
            key, old = self._register(event.customer_id, event.data.get("txn_id"))
            return old if key is not None and key[1] == "posted" else event.day
        return event.day

    def _mark(self, dirty, cid, months=(), from_day=None, everything=False):
        entry = dirty.setdefault(cid, {"months": set(), "from": None, "all": False})
        entry["months"].update(months)
        if everything:
            entry["all"] = True
        if from_day is not None and (entry["from"] is None or from_day < entry["from"]):
            entry["from"] = from_day
        if self.connection.execute("SELECT 1 FROM customers WHERE customer_id = ?", (cid,)).fetchone() is None:
            entry["all"] = True  # a new customer gets every retained checkpoint

    def _apply_event(self, event, dirty):
        connection = self.connection
        cid = event.customer_id
        if event.type in ("transaction.posted", "transaction.corrected", "transaction.reversed"):
            if event.type == "transaction.reversed":
                txn, txn_id = None, event.data["txn_id"]
                key, day = (event.version, "reversed", event.id), event.day
            else:
                txn = events_module.transaction_of(event, self.taxonomy)
                txn_id, key, day = txn.txn_id, (event.version, "posted", event.id), txn.posted_date
            old_key, old_day = self._register(cid, txn_id)
            months, dates = set(), [day]
            if old_key is None or beats(key, old_key):
                if old_key is not None and old_key[1] == "posted":
                    connection.execute("DELETE FROM ledger WHERE customer_id = ? AND txn_id = ?", (cid, txn_id))
                    months.add(_month(old_day))
                    dates.append(old_day)
                connection.execute(
                    "INSERT OR REPLACE INTO txn_registers (customer_id, txn_id, version, status, event_id, posted_date) "
                    "VALUES (?, ?, ?, ?, ?, ?)", (cid, txn_id, key[0], key[1], key[2], _iso(day)))
                if txn is not None:
                    connection.execute(
                        "INSERT INTO ledger ({}) VALUES ({})".format(", ".join(profile.LEDGER_COLUMNS),
                                                                     ", ".join("?" * len(profile.LEDGER_COLUMNS))),
                        profile.ledger_row(txn))
                    months.add(_month(day))
            self._mark(dirty, cid, months, min(dates))
        elif event.type == "customer.updated":
            customer = events_module.customer_of(event, self.taxonomy.base_currency)
            row = connection.execute(
                "SELECT version, event_id FROM customer_versions WHERE customer_id = ? AND effective_from = ?",
                (cid, _iso(event.day))).fetchone()
            if row is None or version_beats((event.version, event.id), (row[0], row[1])):
                connection.execute(
                    "INSERT OR REPLACE INTO customer_versions (customer_id, effective_from, version, event_id, "
                    "account_open_date, home_country, home_currency) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (cid, _iso(event.day), event.version, event.id, _iso(customer.account_open_date),
                     customer.home_country, customer.home_currency))
                months = {(int(m[:4]), int(m[5:7])) for (m,) in connection.execute(
                    "SELECT DISTINCT substr(posted_date, 1, 7) FROM ledger WHERE customer_id = ? AND posted_date >= ?",
                    (cid, windows.month_bounds(_month(event.day))[0].isoformat()))}
                self._mark(dirty, cid, months, event.day)
            else:
                self._mark(dirty, cid)
        else:  # account.closed
            row = connection.execute("SELECT closed_on FROM closures WHERE customer_id = ?", (cid,)).fetchone()
            if row is None or event.day < parse_date(row[0]):
                connection.execute("INSERT OR REPLACE INTO closures (customer_id, closed_on) VALUES (?, ?)",
                                   (cid, _iso(event.day)))
            self._mark(dirty, cid, (), event.day)

    def _affected(self, entry):
        if entry is None:
            return set()
        days = lifecycle_module.checkpoints(self.as_of, self.taxonomy.lifecycle_months)
        if entry["all"]:
            return set(days)
        if entry["from"] is None:
            return set()
        return {d for d in days if d >= entry["from"]}

    def _flush(self, dirty):
        for cid, entry in dirty.items():
            affected = self._affected(entry) if self.as_of is not None else None
            _write_customer(self.connection, self.taxonomy, cid, self.as_of, entry["months"],
                            affected if self.as_of is not None else None)
        dirty.clear()

    def _tick(self, day, dirty):
        if self.as_of is not None and day <= self.as_of:
            return
        connection = self.connection
        # Bring the buckets of customers changed so far up to date first.
        for cid, entry in dirty.items():
            versions = profile.load_versions(connection, cid, self.taxonomy.base_currency)
            data = profile.customer_data(self.taxonomy, cid, versions, profile.load_closed_on(connection, cid),
                                         profile.load_transactions(connection, cid),
                                         profile.load_buckets(connection, cid, skip_months=entry["months"]))
            profile.write_buckets(connection, cid, data, entry["months"])
        old_days = set(lifecycle_module.checkpoints(self.as_of, self.taxonomy.lifecycle_months)) if self.as_of else set()
        self.as_of = day
        new_days = set(lifecycle_module.checkpoints(day, self.taxonomy.lifecycle_months)) - old_days
        self._prune()
        profile.write_meta(connection, _meta_values(self.taxonomy, day, self.lateness_days, store_module.STATE_READY))
        customers = [row[0] for row in connection.execute("SELECT customer_id FROM customers ORDER BY customer_id")]
        for cid in sorted(set(customers) | set(dirty)):
            entry = dirty.get(cid)
            affected = new_days | self._affected(entry)
            _write_customer(connection, self.taxonomy, cid, day, months=set(), affected=affected)
        dirty.clear()

    def _prune(self):
        start = self._start()
        if start is not None:
            prune(self.connection, start)


def export_state(connection):
    """The canonical dump of the tables the invariant compares."""
    return store_module.export(connection, tables=STATE_TABLES)

"""The core property of the plugin: for any seeded random order of the same
events, with duplicates, late arrivals within the allowed lateness, restarts
and crashes, the incrementally maintained store equals a batch rebuild over
the same set of events.

The number of seeds is small by default and larger in CI:
CT_PROPERTY_SEEDS=60 python3 -m unittest tests.test_incremental
"""

import datetime
import os
import random
import shutil
import tempfile
import unittest

from engine import events as ev
from engine import store as store_module
from engine.incremental import STATE_TABLES, Follower, export_state, rebuild_from_events
from tests.helpers import TAXONOMY

LATENESS = 3
START = datetime.date(2026, 7, 10)
END = datetime.date(2026, 9, 30)
LONG_START = datetime.date(2026, 2, 1)  # long enough for monthly rules and lifecycle changes
SEEDS = int(os.environ.get("CT_PROPERTY_SEEDS", "4"))
LONG_SEEDS = int(os.environ.get("CT_PROPERTY_LONG_SEEDS", "1"))
CHANNELS = (("card_pos", "groceries"), ("card_pos", "dining"), ("card_online", "shopping"),
            ("mobile_app", "transfer_out"), ("atm", "cash_withdrawal"), ("internet_banking", "utilities"))


class Stream(object):
    """A seeded event stream and the effective date of every event."""

    def __init__(self, seed, customers=7, start=START):
        self.rng = random.Random(seed)
        self.start = start
        self.events = []        # (event dict, effective date)
        self.counter = 0
        span = (END - start).days

        def day(offset):
            return start + datetime.timedelta(days=offset)
        for c in range(customers):
            cid = "P{:03d}".format(c)
            opened = datetime.date(2024, 1, 1) + datetime.timedelta(days=self.rng.randint(0, 900))
            self._add("customer.updated", datetime.date(2024, 1, 1), cid, {
                "account_open_date": opened.isoformat(), "home_country": "US", "home_currency": "USD"},
                effective=None)
            balance = self.rng.randint(100, 4000) if self.rng.random() < 0.6 else None
            for offset in range(span + 1):
                when = day(offset)
                if when.day == 25 and self.rng.random() < 0.9:
                    balance = self._txn(cid, when, "credit", "incoming", "salary", "SYN-EMPLOYER-00{}".format(c % 3),
                                        str(2000 + 100 * (c % 4)), balance)
                for _ in range(self.rng.choice((0, 0, 0, 1, 1, 2))):
                    channel, category = self.rng.choice(CHANNELS)
                    abroad = self.rng.random() < 0.05
                    balance = self._txn(cid, when, "debit", channel, category,
                                        "SYN-MERCHANT-{:04d}".format(self.rng.randint(1, 30)),
                                        "{:.2f}".format(self.rng.uniform(5, 400)), balance,
                                        currency="EUR" if abroad else "USD", country="FR" if abroad else "US")
            if c == 1:  # a mid-stream change of home country, flipping is_foreign_* for later months
                self._add("customer.updated", day(30), cid, {
                    "account_open_date": opened.isoformat(), "home_country": "FR", "home_currency": "USD"}, version=1)
            if c == 2:
                self._add("account.closed", day(span - 12), cid, {})
        tick_day = start - datetime.timedelta(days=1)
        while tick_day <= END:
            self._add("clock.tick", tick_day, None, {})
            tick_day += datetime.timedelta(days=self.rng.choice((1, 1, 1, 1, 2, 3)))
        self._add("clock.tick", END, None, {}, event_id="tick-final")

    def _id(self):
        self.counter += 1
        return "e{:06d}".format(self.counter)

    def _add(self, kind, when, cid, data, version=0, effective="same", event_id=None):
        raw = ev.make(event_id or self._id(), kind, when, cid, data, version)
        self.events.append((raw, when if effective == "same" else effective))
        return raw

    def _txn(self, cid, when, direction, channel, category, counterparty, amount, balance, currency="USD",
             country="US"):
        txn_id = "{}-{}".format(cid, self.counter)
        if balance is not None:
            change = float(amount) if currency == "USD" else float(amount) * 1.10
            balance = round(balance + (change if direction == "credit" else -change), 2)
        data = {"txn_id": txn_id, "amount": amount, "currency": currency, "direction": direction,
                "channel": channel, "category": category, "counterparty": counterparty, "txn_country": country}
        if balance is not None:
            data.update(balance_after="{:.2f}".format(balance), balance_currency="USD")
        self._add("transaction.posted", when, cid, data)
        roll = self.rng.random()
        if roll < 0.10:  # a correction: new amount, sometimes a new category or a date across a month end
            image = dict(data, amount="{:.2f}".format(float(amount) * self.rng.uniform(0.5, 1.5)))
            moved = when
            if self.rng.random() < 0.3:
                image["category"] = self.rng.choice(("groceries", "shopping", "dining"))
            if when.day >= 28 and self.rng.random() < 0.7:
                moved = when + datetime.timedelta(days=4)
            image["posted_date"] = moved.isoformat()
            self._add("transaction.corrected", when + datetime.timedelta(days=1), cid, image, version=1,
                      effective=min(when, moved))
        elif roll < 0.15:
            self._add("transaction.reversed", when + datetime.timedelta(days=1), cid, {"txn_id": txn_id},
                      version=2, effective=when)
        elif roll < 0.17:  # a second posting of the same transaction with a later id: the first one wins
            self._add("transaction.posted", when, cid, dict(data, amount="1.00"))
        return balance

    def unique(self):
        return [raw for raw, _ in self.events]


def deliveries(stream, seed):
    """Batches in a random order that never exceeds the allowed lateness:
    every event arrives between 2 days early and LATENESS days after its
    effective date (before any tick if it has none); some arrive twice; each
    day's tick comes last that day."""
    rng = random.Random(seed * 7919 + 1)
    by_day = {}
    first = stream.start - datetime.timedelta(days=2)
    for raw, effective in stream.events:
        if raw["type"] == "clock.tick":
            by_day.setdefault(datetime.date.fromisoformat(raw["time"]), []).append(("tick", raw))
            continue
        copies = 2 if rng.random() < 0.1 else 1
        for _ in range(copies):
            if effective is None:
                when = first
            else:
                when = effective + datetime.timedelta(days=rng.randint(-2, LATENESS))
                when = max(when, first)
            by_day.setdefault(when, []).append(("event", raw))
    batches = []
    for when in sorted(by_day):
        items = by_day[when]
        plain = [raw for kind, raw in items if kind == "event"]
        rng.shuffle(plain)
        ticks = [raw for kind, raw in items if kind == "tick"]
        while plain:
            size = rng.randint(1, 6)
            batches.append(plain[:size])
            plain = plain[size:]
        for tick in ticks:
            batches.append([tick])
    return batches


class CrashingFollower(Follower):
    """Raises part-way through a batch, after some events were applied."""

    def _flush(self, dirty):
        raise RuntimeError("simulated crash")


def run_incremental(path, batches, seed):
    rng = random.Random(seed * 104729 + 3)
    follower = Follower(path, TAXONOMY, LATENESS, clock=lambda: "t")
    try:
        for batch in batches:
            if rng.random() < 0.03:
                follower.close()
                crashing = CrashingFollower(path, TAXONOMY, LATENESS, clock=lambda: "t")
                try:
                    crashing.apply(batch)
                except RuntimeError:
                    pass
                crashing.close()
                follower = Follower(path, TAXONOMY, LATENESS, clock=lambda: "t")
            follower.apply(batch)
            if rng.random() < 0.05:
                follower.close()
                follower = Follower(path, TAXONOMY, LATENESS, clock=lambda: "t")
        late = follower.connection.execute("SELECT COUNT(*) FROM late_events").fetchone()[0]
        return export_state(follower.connection), late
    finally:
        follower.close()


def run_batch(path, raw_events):
    rebuild_from_events(raw_events, path, TAXONOMY, lateness_days=LATENESS, clock=lambda: "t")
    connection = store_module.open_store(path, TAXONOMY)
    try:
        return export_state(connection)
    finally:
        connection.close()


def first_difference(a, b):
    for x, y in zip(a.splitlines(), b.splitlines()):
        if x != y:
            return "incremental: {}\nbatch:       {}".format(x[:400], y[:400])
    return "lengths differ: {} vs {} lines".format(len(a.splitlines()), len(b.splitlines()))


def _differs(stream, seed, folder, tag):
    inc, _ = run_incremental(os.path.join(folder, "shrink-i-{}.db".format(tag)), deliveries(stream, seed), seed)
    bat = run_batch(os.path.join(folder, "shrink-b-{}.db".format(tag)), stream.unique())
    return inc != bat


def shrink(stream, seed, folder, budget=200):
    """Drop whole customers, then single events, while the failure persists;
    return the smallest failing list of (event, effective date)."""
    attempts = 0
    for cid in sorted({raw.get("customer_id") for raw, _ in stream.events} - {None}):
        trial = [(raw, eff) for raw, eff in stream.events if raw.get("customer_id") != cid]
        saved, stream.events = stream.events, trial
        attempts += 1
        if not _differs(stream, seed, folder, attempts):
            stream.events = saved
    index = 0
    while index < len(stream.events) and attempts < budget:
        if stream.events[index][0]["type"] == "clock.tick":
            index += 1
            continue
        saved = stream.events
        stream.events = saved[:index] + saved[index + 1:]
        attempts += 1
        if not _differs(stream, seed, folder, attempts):
            stream.events = saved
            index += 1
    return stream.events


class IncrementalEqualsBatch(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="tagging-prop-")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _check(self, seed, stream=None):
        stream = stream or Stream(seed)
        inc_path = os.path.join(self.dir, "inc-{}.db".format(seed))
        bat_path = os.path.join(self.dir, "bat-{}.db".format(seed))
        incremental_dump, late = run_incremental(inc_path, deliveries(stream, seed), seed)
        batch_dump = run_batch(bat_path, stream.unique())
        self.assertEqual(late, 0, "seed {}: an event was late inside the bound".format(seed))
        if incremental_dump != batch_dump:
            kept = shrink(stream, seed, self.dir)
            self.fail("seed {}: incremental store differs from the batch rebuild\n{}\nsmallest failing set: {} "
                      "events, customers {}".format(seed, first_difference(incremental_dump, batch_dump), len(kept),
                                                   sorted({raw.get("customer_id") for raw, _ in kept} - {None})))

    def test_any_order_within_the_bound_equals_the_batch_rebuild(self):
        for seed in range(1, SEEDS + 1):
            with self.subTest(seed=seed):
                self._check(seed)

    def test_a_long_stream_with_monthly_tags_and_lifecycle_changes(self):
        for seed in range(1001, 1001 + LONG_SEEDS):
            with self.subTest(seed=seed):
                self._check(seed, Stream(seed, customers=6, start=LONG_START))

    def test_the_stream_exercises_every_kind_of_event(self):
        stream = Stream(1)
        kinds = {raw["type"] for raw in stream.unique()}
        self.assertEqual(kinds, set(ev.TYPES))
        batches = deliveries(stream, 1)
        flat = [raw["id"] for batch in batches for raw in batch]
        self.assertGreater(len(flat), len(set(flat)), "some events must arrive twice")
        tick_days = sorted(raw["time"] for raw in stream.unique() if raw["type"] == "clock.tick")
        gaps = [(datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days
                for a, b in zip(tick_days, tick_days[1:])]
        self.assertGreater(max(gaps), 1, "some ticks must skip days")


class Lateness(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="tagging-late-")
        self.path = os.path.join(self.dir, "s.db")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _events(self):
        out = [ev.make("c1", "customer.updated", "2024-01-01", "L1",
                       {"account_open_date": "2024-01-01", "home_country": "US", "home_currency": "USD"})]
        for d in range(1, 31):
            out.append(ev.make("t{}".format(d), "transaction.posted", datetime.date(2026, 8, d), "L1",
                               {"txn_id": "x{}".format(d), "amount": "-20.00", "currency": "USD",
                                "channel": "card_pos", "category": "groceries"}))
        return out

    def test_an_event_beyond_the_bound_is_kept_aside_and_not_applied(self):
        follower = Follower(self.path, TAXONOMY, LATENESS, clock=lambda: "t")
        try:
            accepted = self._events()
            follower.apply(accepted + [ev.make("tick-sep-10", "clock.tick", "2026-09-10")])
            late = ev.make("late-1", "transaction.posted", "2026-08-15", "L1",
                           {"txn_id": "late", "amount": "-999.00", "currency": "USD", "channel": "card_pos",
                            "category": "groceries"})
            counts = follower.apply([late])
            self.assertEqual(counts["late"], 1)
            row = follower.connection.execute("SELECT reason, as_of FROM late_events").fetchone()
            self.assertEqual(row, ("beyond_allowed_lateness", "2026-09-10"))
            self.assertIsNone(follower.connection.execute(
                "SELECT 1 FROM ledger WHERE txn_id = 'late'").fetchone())
            incremental_dump = export_state(follower.connection)
        finally:
            follower.close()
        batch = run_batch(os.path.join(self.dir, "b.db"),
                          accepted + [ev.make("tick-sep-10", "clock.tick", "2026-09-10")])
        self.assertEqual(incremental_dump, batch)

    def test_an_event_inside_the_bound_is_applied(self):
        follower = Follower(self.path, TAXONOMY, LATENESS, clock=lambda: "t")
        try:
            follower.apply(self._events() + [ev.make("tick", "clock.tick", "2026-09-02")])
            counts = follower.apply([ev.make("in-time", "transaction.posted", "2026-08-31", "L1", {
                "txn_id": "ok", "amount": "-5.00", "currency": "USD", "channel": "card_pos", "category": "groceries"})])
            self.assertEqual((counts["applied"], counts["late"]), (1, 0))
        finally:
            follower.close()


class Idempotency(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="tagging-idem-")
        self.path = os.path.join(self.dir, "s.db")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_duplicates_are_skipped_and_conflicts_refused(self):
        posted = ev.make("p1", "transaction.posted", "2026-09-01", "D1",
                         {"txn_id": "a", "amount": "-10.00", "currency": "USD"})
        follower = Follower(self.path, TAXONOMY, LATENESS, clock=lambda: "t")
        try:
            first = follower.apply([posted, posted])
            self.assertEqual((first["applied"], first["duplicate"]), (1, 1))
            changed = dict(posted, data=dict(posted["data"], amount="-99.00"))
            second = follower.apply([changed])
            self.assertEqual(second["late"], 1)
            self.assertEqual(follower.connection.execute("SELECT reason FROM late_events").fetchone()[0],
                             "conflicting_duplicate")
            self.assertEqual(follower.connection.execute("SELECT amount_cents FROM ledger").fetchone()[0], 1000)
        finally:
            follower.close()

    def test_unusable_events_are_rejected_with_a_reason(self):
        follower = Follower(self.path, TAXONOMY, LATENESS, clock=lambda: "t")
        try:
            counts = follower.apply([
                ev.make("bad-amount", "transaction.posted", "2026-09-01", "R1", {"txn_id": "a", "amount": "abc",
                                                                                 "currency": "USD"}),
                ev.make("bad-currency", "transaction.posted", "2026-09-01", "R1", {"txn_id": "b", "amount": "-1",
                                                                                   "currency": "ZZZ"}),
                {"schema": "nope"},
                "not json",
                ev.make("fine", "transaction.posted", "2026-09-01", "R1", {"txn_id": "c", "amount": "-1",
                                                                          "currency": "USD"}),
            ])
            self.assertEqual((counts["rejected"], counts["applied"]), (4, 1))
            reasons = dict(follower.connection.execute("SELECT event_id, reason FROM rejected_events"))
            self.assertEqual(reasons["bad-amount"], "bad_or_missing_amount")
            self.assertEqual(reasons["bad-currency"], "unknown_currency")
            follower.apply([ev.make("tick", "clock.tick", "2026-09-02")])
            notes = follower.connection.execute("SELECT notes FROM customers WHERE customer_id = 'R1'").fetchone()[0]
            self.assertIn('"bad_or_missing_amount":1', notes)
        finally:
            follower.close()


class Ticks(unittest.TestCase):
    def test_an_older_tick_changes_nothing_and_a_skipped_month_end_is_checked(self):
        folder = tempfile.mkdtemp(prefix="tagging-tick-")
        try:
            path = os.path.join(folder, "s.db")
            follower = Follower(path, TAXONOMY, LATENESS, clock=lambda: "t")
            try:
                follower.apply([ev.make("c", "customer.updated", "2024-01-01", "K1", {
                    "account_open_date": "2024-01-01", "home_country": "US", "home_currency": "USD"}),
                    ev.make("t1", "clock.tick", "2026-08-29")])
                tables = [t for t in STATE_TABLES if t != "events_seen"]
                before = store_module.export(follower.connection, tables)
                follower.apply([ev.make("t0", "clock.tick", "2026-08-20")])
                self.assertEqual(store_module.export(follower.connection, tables), before)
                follower.apply([ev.make("t2", "clock.tick", "2026-09-02")])  # skips over August 31
                days = [row[0] for row in follower.connection.execute(
                    "SELECT checkpoint FROM checkpoint_tags WHERE customer_id = 'K1' ORDER BY checkpoint")]
                self.assertEqual(days[-1], "2026-08-31")
                self.assertEqual(follower.as_of, datetime.date(2026, 9, 2))
            finally:
                follower.close()
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class Prevalence(unittest.TestCase):
    def test_prevalence_is_recorded_when_a_tick_moves_the_as_of_date_only(self):
        folder = tempfile.mkdtemp(prefix="tagging-prevalence-")
        try:
            follower = Follower(os.path.join(folder, "s.db"), TAXONOMY, LATENESS, clock=lambda: "t")
            try:
                follower.apply([ev.make("c", "customer.updated", "2024-01-01", "P1", {
                    "account_open_date": "2024-01-01", "home_country": "US", "home_currency": "USD"}),
                    ev.make("t1", "clock.tick", "2026-08-31")])
                follower.apply([ev.make("p", "transaction.posted", "2026-09-01", "P1",
                                        {"txn_id": "a", "amount": "-10.00", "currency": "USD"})])
                follower.apply([ev.make("t0", "clock.tick", "2026-08-20")])  # older: the as-of does not move
                follower.apply([ev.make("t2", "clock.tick", "2026-09-30")])
                runs = [row[0] for row in follower.connection.execute("SELECT run_id FROM runs ORDER BY run_id")]
                recorded = [row[0] for row in follower.connection.execute(
                    "SELECT DISTINCT run_id FROM run_tags ORDER BY run_id")]
                bands = follower.connection.execute(
                    "SELECT SUM(customers) FROM run_spread WHERE run_id = ?", (runs[-1],)).fetchone()[0]
                tags = follower.connection.execute(
                    "SELECT COUNT(*) FROM run_tags WHERE run_id = ?", (runs[-1],)).fetchone()[0]
            finally:
                follower.close()
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        self.assertEqual(len(runs), 4)
        self.assertEqual(recorded, [runs[0], runs[3]])
        self.assertEqual((bands, tags), (1, len(TAXONOMY.by_id)))


class ReadOnlyWhileFollowing(unittest.TestCase):
    def test_a_reader_can_open_the_store_during_and_after_following(self):
        folder = tempfile.mkdtemp(prefix="tagging-wal-")
        try:
            path = os.path.join(folder, "s.db")
            follower = Follower(path, TAXONOMY, LATENESS, clock=lambda: "t")
            try:
                follower.apply([ev.make("t", "clock.tick", "2026-09-02")])
                reader = store_module.open_store(path, TAXONOMY)  # while the follower holds it in WAL mode
                self.assertEqual(store_module.meta(reader)["as_of"], "2026-09-02")
                reader.close()
            finally:
                follower.close()
            reader = store_module.open_store(path, TAXONOMY)  # after: back in rollback-journal mode
            self.assertEqual(reader.execute("PRAGMA journal_mode").fetchone()[0], "delete")
            reader.close()
            self.assertFalse(os.path.exists(path + "-wal") and os.path.getsize(path + "-wal") > 0)
        finally:
            shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

"""Change-feed adapters, checkpoints and restart, and the follow command."""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from engine import events as ev
from engine import feeds
from engine import store as store_module
from engine.incremental import Follower, export_state, rebuild_from_events
from tests.helpers import ROOT, TAXONOMY


def sample_events(n=30):
    out = [ev.make("c1", "customer.updated", "2024-01-01", "F1",
                   {"account_open_date": "2024-01-01", "home_country": "US", "home_currency": "USD"})]
    for k in range(n):
        out.append(ev.make("p{:03d}".format(k), "transaction.posted", "2026-09-{:02d}".format(1 + k % 28), "F1",
                           {"txn_id": "t{}".format(k), "amount": "-12.50", "currency": "USD", "channel": "card_pos",
                            "category": "groceries"}))
    out.append(ev.make("tick", "clock.tick", "2026-09-30"))
    return out


def write_jsonl(path, events, partial_tail=None):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        for raw in events:
            handle.write(json.dumps(raw) + "\n")
        if partial_tail is not None:
            handle.write(partial_tail)  # a line still being written: no newline yet


class Jsonl(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="tagging-feed-")
        self.feed_path = os.path.join(self.dir, "feed.jsonl")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_reads_complete_lines_only_and_resumes_from_the_offset(self):
        events = sample_events(5)
        write_jsonl(self.feed_path, events, partial_tail='{"schema": "customer-tag')
        feed = feeds.JsonlFeed(self.feed_path)
        first, position = feed.read(0, 3)
        self.assertEqual(len(first), 3)
        rest, end = feed.read(position, 100)
        self.assertEqual(len(first) + len(rest), len(events))
        again, same = feed.read(end, 100)
        self.assertEqual((again, same), ([], end))  # the half-written line is not read

    def test_a_replaced_file_is_noticed(self):
        write_jsonl(self.feed_path, sample_events(5))
        store_path = os.path.join(self.dir, "s.db")
        follower = Follower(store_path, TAXONOMY, clock=lambda: "t")
        try:
            feeds.follow(follower, feeds.JsonlFeed(self.feed_path), batch_size=2)
            os.remove(self.feed_path)
            write_jsonl(self.feed_path, sample_events(2)[::-1])
            with self.assertRaises(feeds.FeedError):
                feeds.follow(follower, feeds.JsonlFeed(self.feed_path))
        finally:
            follower.close()

    def test_a_truncated_file_is_refused(self):
        write_jsonl(self.feed_path, sample_events(5))
        with self.assertRaises(feeds.FeedError):
            feeds.JsonlFeed(self.feed_path).read(10 ** 6, 10)


class Outbox(unittest.TestCase):
    def test_polls_by_sequence_number_read_only(self):
        folder = tempfile.mkdtemp(prefix="tagging-outbox-")
        try:
            outbox = os.path.join(folder, "outbox.db")
            connection = sqlite3.connect(outbox)
            connection.execute("CREATE TABLE outbox (seq INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT NOT NULL)")
            connection.executemany("INSERT INTO outbox (event) VALUES (?)", [(json.dumps(e),) for e in sample_events(8)])
            connection.commit()
            connection.close()
            feed = feeds.OutboxFeed(outbox)
            batch, position = feed.read(0, 4)
            self.assertEqual((len(batch), position), (4, 4))
            batch, position = feed.read(position, 100)
            self.assertEqual(position, 10)
            store_path = os.path.join(folder, "s.db")
            follower = Follower(store_path, TAXONOMY, clock=lambda: "t")
            try:
                totals = feeds.follow(follower, feed, batch_size=3)
                self.assertEqual(totals["applied"], 10)
                self.assertEqual(follower.position(feed.name)[0], "10")
            finally:
                follower.close()
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class Restart(unittest.TestCase):
    def test_a_crash_mid_feed_resumes_from_the_committed_position(self):
        folder = tempfile.mkdtemp(prefix="tagging-restart-")
        try:
            events = sample_events(40)
            feed_path = os.path.join(folder, "feed.jsonl")
            write_jsonl(feed_path, events)

            class Crash(Follower):
                calls = 0

                def apply(self, raw_events, **kwargs):
                    Crash.calls += 1
                    if Crash.calls == 3:
                        raise RuntimeError("power cut")
                    return Follower.apply(self, raw_events, **kwargs)

            path = os.path.join(folder, "s.db")
            crashing = Crash(path, TAXONOMY, clock=lambda: "t")
            with self.assertRaises(RuntimeError):
                feeds.follow(crashing, feeds.JsonlFeed(feed_path), batch_size=7)
            position = crashing.position("jsonl:feed.jsonl")[0]
            crashing.close()
            self.assertIsNotNone(position)
            resumed = Follower(path, TAXONOMY, clock=lambda: "t")
            try:
                feeds.follow(resumed, feeds.JsonlFeed(feed_path), batch_size=7)
                dump = export_state(resumed.connection)
                applied = resumed.connection.execute("SELECT SUM(events_applied) FROM runs").fetchone()[0]
            finally:
                resumed.close()
            self.assertEqual(applied, len(events))  # exactly once
            batch_path = os.path.join(folder, "b.db")
            rebuild_from_events(events, batch_path, TAXONOMY, clock=lambda: "t")
            connection = store_module.open_store(batch_path, TAXONOMY)
            try:
                self.assertEqual(dump, export_state(connection))
            finally:
                connection.close()
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class FollowCommand(unittest.TestCase):
    def test_follow_from_a_csv_built_store(self):
        folder = tempfile.mkdtemp(prefix="tagging-follow-")
        env = dict(os.environ, PYTHONPATH=ROOT, PYTHONDONTWRITEBYTECODE="1")
        try:
            store_path = os.path.join(folder, "p.db")
            data = os.path.join(ROOT, "data")
            result = subprocess.run([sys.executable, "-m", "engine.build", "--rebuild", "--customers",
                                     os.path.join(data, "customers.csv"), "--transactions",
                                     os.path.join(data, "transactions.csv"), "--store", store_path],
                                    cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    universal_newlines=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            feed_path = os.path.join(folder, "feed.jsonl")
            write_jsonl(feed_path, [
                ev.make("live-1", "transaction.posted", "2026-10-01", "C0001",
                        {"txn_id": "LIVE-1", "amount": "-25.00", "currency": "USD", "channel": "card_pos",
                         "category": "groceries"}),
                ev.make("tick-oct-1", "clock.tick", "2026-10-01")])
            result = subprocess.run([sys.executable, "-m", "engine.build", "--follow", "--store", store_path,
                                     "--jsonl", feed_path], cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, universal_newlines=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("2 applied", result.stdout)
            self.assertIn("as of 2026-10-01", result.stdout)
            connection = store_module.open_store(store_path, TAXONOMY)
            try:
                self.assertEqual(store_module.meta(connection)["as_of"], "2026-10-01")
                self.assertIsNotNone(connection.execute(
                    "SELECT 1 FROM ledger WHERE txn_id = 'LIVE-1'").fetchone())
            finally:
                connection.close()
            # Following again reads nothing new.
            result = subprocess.run([sys.executable, "-m", "engine.build", "--follow", "--store", store_path,
                                     "--jsonl", feed_path], cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, universal_newlines=True)
            self.assertIn("0 events read", result.stdout)
        finally:
            shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

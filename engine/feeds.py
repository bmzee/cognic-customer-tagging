"""Change-feed adapters: where events come from. No message broker needed.

Two adapters share one small interface, read(position, limit) ->
(events, new_position), plus a name and an identity:

    JsonlFeed    follows a JSONL file, one event per line. The position is
                 the byte offset after the last complete line read, so a line
                 still being written is never read half-way. The identity is
                 the file's device and inode plus a hash of its first line,
                 so a replaced or rotated file is noticed instead of being
                 read from the wrong offset.
    OutboxFeed   polls a SQLite outbox table (seq INTEGER PRIMARY KEY
                 AUTOINCREMENT, event TEXT) through a read-only connection.
                 The position is the last seq read.

A bank-side bridge appends its change data capture to either one (see
engine/events.py for how CDC maps onto events). follow() reads batches and
hands each to the Follower together with the new position, which is stored
in the same transaction as the batch's effects.
"""

import hashlib
import os
import sqlite3

from . import store as store_module

MAX_LINE_BYTES = 65536


class FeedError(RuntimeError):
    """The feed cannot be read from the stored position."""


class JsonlFeed(object):
    def __init__(self, path, name=None):
        self.path = path
        self.name = name or "jsonl:" + os.path.basename(path)

    def identity(self):
        info = os.stat(self.path)
        with open(self.path, "rb") as handle:
            first = handle.readline(MAX_LINE_BYTES)
        return "{}:{}:{}".format(info.st_dev, info.st_ino, hashlib.sha256(first).hexdigest()[:16])

    def read(self, position, limit):
        offset = int(position or 0)
        size = os.path.getsize(self.path)
        if offset > size:
            raise FeedError("{} is shorter than the stored position {}: it was truncated or replaced".format(
                self.name, offset))
        events = []
        with open(self.path, "rb") as handle:
            handle.seek(offset)
            while len(events) < limit:
                line = handle.readline(MAX_LINE_BYTES + 1)
                if not line or not line.endswith(b"\n"):
                    break  # end of file, or a line still being written
                offset += len(line)
                text = line.strip()
                if text:
                    events.append(text.decode("utf-8", "replace"))
        return events, offset


class OutboxFeed(object):
    def __init__(self, path, table="outbox", name=None):
        if not table.isidentifier():
            raise FeedError("bad outbox table name")
        self.path = path
        self.table = table
        self.name = name or "outbox:" + os.path.basename(path)

    def identity(self):
        return "outbox:{}".format(self.table)

    def read(self, position, limit):
        connection = store_module.connect_ro(self.path) if os.path.isfile(self.path) else None
        if connection is None:
            raise FeedError("no outbox at {}".format(self.path))
        try:
            rows = connection.execute("SELECT seq, event FROM {} WHERE seq > ? ORDER BY seq LIMIT ?".format(self.table),
                                      (int(position or 0), limit)).fetchall()
        except sqlite3.DatabaseError as exc:
            raise FeedError("cannot read the outbox: {}".format(exc))
        finally:
            connection.close()
        if not rows:
            return [], int(position or 0)
        return [event for _, event in rows], rows[-1][0]


def follow(follower, feed, batch_size=500, max_batches=None):
    """Read and apply batches until the feed has nothing new (or max_batches).
    Returns the summed counts."""
    totals = {"batches": 0, "read": 0, "applied": 0, "duplicate": 0, "rejected": 0, "late": 0}
    position, identity = follower.position(feed.name)
    current = feed.identity()
    if identity and identity != current:
        raise FeedError("{} is not the feed this store was following (it was replaced or rotated); reset the "
                        "feed position or rebuild".format(feed.name))
    while max_batches is None or totals["batches"] < max_batches:
        events, new_position = feed.read(position, batch_size)
        if not events and str(new_position) == str(position or 0):
            break
        counts = follower.apply(events, feed=feed.name, position=new_position, identity=current)
        totals["batches"] += 1
        for key in ("read", "applied", "duplicate", "rejected", "late"):
            totals[key] += counts[key]
        position = new_position
        if not events:
            break
    return totals

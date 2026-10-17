"""The builder: produce or update the profile store. The only writer of the store.

python3 -m engine.build --rebuild --customers C.csv --transactions T.csv --store profile.db [--as-of DATE]
python3 -m engine.build --rebuild --events events.jsonl --store profile.db [--as-of DATE]
    Build the whole store from the read-only data copy, or from a file of
    events. The CSV copy is turned into events first, so both are one batch
    path. The store is written to a temporary file and renamed into place
    only when complete, so a reader never sees a half-built store.

python3 -m engine.build --follow --store profile.db (--jsonl FEED.jsonl | --outbox OUTBOX.db)
    Apply new events from a change feed: everything available, in batches,
    then exit. Each batch is one transaction holding its effects and the
    feed position, so a crash loses nothing and repeats nothing. A host
    scheduler (Cognic's planned watchers) runs it again when events arrive.

python3 -m engine.build --export --store profile.db [--out FILE]
    Print a canonical dump of the store (every table; runs without its clock
    columns). The same inputs and as-of date always give the same bytes.

The builder writes only the plugin's own store (a "private" effect): it
never writes the bank's data, and it refuses to write over an input file.
Everything it computes is deterministic; only the runs table's started_at
and finished_at read the clock, for the audit trail.
"""

import argparse
import datetime
import hashlib
import io
import os
import sys

from . import DEFAULT_TAXONOMY, DataError, TaxonomyError, load_taxonomy
from . import events as events_module
from . import store as store_module


def utc_now():
    """Wall-clock time for the runs table only; never used in a calculation.
    SOURCE_DATE_EPOCH, when set, fixes it, so a store built into an image is
    byte-for-byte reproducible."""
    fixed = os.environ.get("SOURCE_DATE_EPOCH")
    if fixed and fixed.isdigit():
        return datetime.datetime.fromtimestamp(int(fixed), datetime.timezone.utc).isoformat()
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def file_digest(paths):
    digest = hashlib.sha256()
    for path in paths:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _refuse_inputs(store_path, inputs):
    if os.path.abspath(store_path) in {os.path.abspath(p) for p in inputs}:
        raise DataError("refusing to write the store over an input file: {}".format(store_path))


def rebuild(customers_path, transactions_path, store_path, taxonomy=None, as_of=None, clock=utc_now):
    """Build a complete store from the CSV copy. Returns a summary dict."""
    from .incremental import rebuild_from_events
    if taxonomy is None or isinstance(taxonomy, str):
        taxonomy = load_taxonomy(taxonomy or DEFAULT_TAXONOMY)
    _refuse_inputs(store_path, (customers_path, transactions_path))
    sink = {"rejected": [], "notes": {}}
    events = events_module.csv_events(customers_path, transactions_path, taxonomy, as_of, sink)
    return rebuild_from_events(events, store_path, taxonomy, as_of, pre_rejected=sink["rejected"],
                               notes=sink["notes"], snapshot=file_digest([customers_path, transactions_path]),
                               clock=clock)


def read_events_file(path):
    """Yield the events of a JSONL file one line at a time."""
    with io.open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield line.strip()


def rebuild_events(events_path, store_path, taxonomy=None, as_of=None, clock=utc_now):
    """Build a complete store from a JSONL file of events."""
    from .incremental import rebuild_from_events
    if taxonomy is None or isinstance(taxonomy, str):
        taxonomy = load_taxonomy(taxonomy or DEFAULT_TAXONOMY)
    _refuse_inputs(store_path, (events_path,))
    return rebuild_from_events(read_events_file(events_path), store_path, taxonomy, as_of,
                               snapshot=file_digest([events_path]), clock=clock)


def _parse_args(argv):
    parser = argparse.ArgumentParser(prog="python3 -m engine.build", description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--rebuild", action="store_true", help="build the whole store from the CSV copy or events")
    mode.add_argument("--follow", action="store_true", help="apply new events from a change feed, then exit")
    mode.add_argument("--export", action="store_true", help="print a canonical dump of the store")
    parser.add_argument("--store", required=True, help="path to the profile store (SQLite)")
    parser.add_argument("--customers", help="path to customers.csv (with --rebuild)")
    parser.add_argument("--transactions", help="path to transactions.csv (with --rebuild)")
    parser.add_argument("--events", help="a JSONL file of events (with --rebuild)")
    parser.add_argument("--jsonl", help="a JSONL change feed to follow (with --follow)")
    parser.add_argument("--outbox", help="a SQLite outbox database to poll (with --follow)")
    parser.add_argument("--outbox-table", default="outbox", help="the outbox table (default outbox)")
    parser.add_argument("--batch-size", type=int, default=500, help="events per transaction (default 500)")
    parser.add_argument("--max-batches", type=int, help="stop after this many batches")
    parser.add_argument("--lateness-days", type=int, default=3, help="allowed lateness in days (default 3)")
    parser.add_argument("--taxonomy", default=DEFAULT_TAXONOMY, help="path to tags.json")
    parser.add_argument("--as-of", help="YYYY-MM-DD; default: the latest clock tick (or posted date for a CSV copy)")
    parser.add_argument("--out", help="with --export: write the dump here instead of printing it")
    return parser.parse_args(argv)


def _fail(message):
    sys.stderr.write("error: {}\n".format(message))
    return 2


def main(argv=None):
    from . import feeds
    from .incremental import Follower
    args = _parse_args(argv)
    try:
        taxonomy = load_taxonomy(args.taxonomy)
        if args.export:
            connection = store_module.open_store(args.store, taxonomy)
            try:
                text = store_module.export(connection)
            finally:
                connection.close()
            if args.out:
                with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(text)
            else:
                sys.stdout.write(text)
            return 0
        if args.follow:
            if bool(args.jsonl) == bool(args.outbox):
                return _fail("--follow needs exactly one of --jsonl or --outbox")
            source = args.jsonl or args.outbox
            _refuse_inputs(args.store, (source,))
            feed = feeds.JsonlFeed(args.jsonl) if args.jsonl else feeds.OutboxFeed(args.outbox, args.outbox_table)
            follower = Follower(args.store, taxonomy, args.lateness_days)
            try:
                totals = feeds.follow(follower, feed, args.batch_size, args.max_batches)
                as_of = follower.as_of
            finally:
                follower.close()
            sys.stdout.write("followed {}: {batches} batches, {read} events read, {applied} applied, {duplicate} "
                             "duplicates, {rejected} rejected, {late} late; as of {as_of}\n".format(
                                 feed.name, as_of=as_of.isoformat() if as_of else "none yet", **totals))
            return 0
        as_of = None
        if args.as_of:
            try:
                as_of = datetime.datetime.strptime(args.as_of, "%Y-%m-%d").date()
            except ValueError:
                return _fail("--as-of must be YYYY-MM-DD")
        if args.events:
            summary = rebuild_events(args.events, args.store, taxonomy, as_of)
        elif args.customers and args.transactions:
            summary = rebuild(args.customers, args.transactions, args.store, taxonomy, as_of)
        else:
            return _fail("--rebuild needs --customers and --transactions, or --events")
    except (DataError, TaxonomyError, store_module.StoreError, feeds.FeedError, OSError) as exc:
        return _fail(str(exc))
    sys.stdout.write("built {store}: {customers} customers, {transactions} transactions, {tags_held} tags held, "
                     "as of {as_of}, taxonomy {taxonomy_version}\n".format(**summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""The builder: produce or update the profile store. The only writer of the store.

python3 -m engine.build --rebuild --customers C.csv --transactions T.csv --store profile.db [--as-of DATE]
    Build the whole store from the read-only data copy. It is written to a
    temporary file next to --store and renamed into place only when complete,
    so a reader never sees a half-built store.

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
import os
import sys

from . import DEFAULT_TAXONOMY, ENGINE_VERSION, DataError, TaxonomyError, load_taxonomy
from . import data as data_module
from . import profile
from . import store as store_module


def utc_now():
    """Wall-clock time for the runs table only; never used in a calculation."""
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def file_digest(paths):
    digest = hashlib.sha256()
    for path in paths:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def rebuild(customers_path, transactions_path, store_path, taxonomy=None, as_of=None, clock=utc_now):
    """Build a complete store. Returns a summary dict."""
    if taxonomy is None or isinstance(taxonomy, str):
        taxonomy = load_taxonomy(taxonomy or DEFAULT_TAXONOMY)
    inputs = {os.path.abspath(p) for p in (customers_path, transactions_path)}
    if os.path.abspath(store_path) in inputs:
        raise DataError("refusing to write the store over an input file: {}".format(store_path))
    started = clock()
    customers, customer_notes = data_module.load_customers(customers_path, taxonomy.base_currency)
    txns, as_of, run_notes, per_customer = data_module.load_transactions(
        transactions_path, customers, taxonomy, as_of)
    snapshot = file_digest([customers_path, transactions_path])

    temporary = store_path + ".building"
    if os.path.exists(temporary):
        os.remove(temporary)
    connection = store_module.connect_rw(temporary)
    try:
        store_module.apply_migrations(connection)
        connection.execute("BEGIN IMMEDIATE")
        profile.write_meta(connection, [
            ("state", store_module.STATE_BUILDING),
            ("engine_version", ENGINE_VERSION),
            ("taxonomy_version", taxonomy.version),
            ("taxonomy_hash", taxonomy.content_hash),
            ("base_currency", taxonomy.base_currency),
            ("as_of", as_of.isoformat()),
            ("history_months", taxonomy.history_months),
            ("lifecycle_months", taxonomy.lifecycle_months),
            ("retention_start", profile.retention_start(as_of, taxonomy).isoformat()),
        ])
        profile.write_features(connection, taxonomy)
        held = 0
        for cid, customer in customers.items():
            held += profile.write_customer(connection, taxonomy, customer, txns[cid], as_of, per_customer[cid])
        used = sum(len(rows) for rows in txns.values())
        connection.execute(
            "INSERT INTO runs (kind, as_of, engine_version, taxonomy_version, taxonomy_hash, input_snapshot_hash, "
            "customers, transactions, tags_held, notes, started_at, finished_at) "
            "VALUES ('rebuild', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (as_of.isoformat(), ENGINE_VERSION, taxonomy.version, taxonomy.content_hash, snapshot, len(customers),
             used, held, store_module.canonical({"customers": customer_notes, "transactions": run_notes}),
             started, clock()))
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
    return {"store": store_path, "as_of": as_of.isoformat(), "customers": len(customers),
            "transactions": used, "tags_held": held, "taxonomy_version": taxonomy.version}


def _parse_args(argv):
    parser = argparse.ArgumentParser(prog="python3 -m engine.build", description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--rebuild", action="store_true", help="build the whole store from the CSV copy")
    mode.add_argument("--export", action="store_true", help="print a canonical dump of the store")
    parser.add_argument("--store", required=True, help="path to the profile store (SQLite)")
    parser.add_argument("--customers", help="path to customers.csv (with --rebuild)")
    parser.add_argument("--transactions", help="path to transactions.csv (with --rebuild)")
    parser.add_argument("--taxonomy", default=DEFAULT_TAXONOMY, help="path to tags.json")
    parser.add_argument("--as-of", help="YYYY-MM-DD; default: the latest posted_date in the transactions")
    parser.add_argument("--out", help="with --export: write the dump here instead of printing it")
    return parser.parse_args(argv)


def _fail(message):
    sys.stderr.write("error: {}\n".format(message))
    return 2


def main(argv=None):
    args = _parse_args(argv)
    try:
        if args.export:
            taxonomy = load_taxonomy(args.taxonomy)
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
        if not args.customers or not args.transactions:
            return _fail("--rebuild needs --customers and --transactions")
        as_of = None
        if args.as_of:
            try:
                as_of = datetime.datetime.strptime(args.as_of, "%Y-%m-%d").date()
            except ValueError:
                return _fail("--as-of must be YYYY-MM-DD")
        summary = rebuild(args.customers, args.transactions, args.store, args.taxonomy, as_of)
    except (DataError, TaxonomyError, store_module.StoreError, OSError) as exc:
        return _fail(str(exc))
    sys.stdout.write("built {store}: {customers} customers, {transactions} transactions, {tags_held} tags held, "
                     "as of {as_of}, taxonomy {taxonomy_version}\n".format(**summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())

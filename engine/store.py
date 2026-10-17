"""The profile store: one SQLite file owned by the plugin.

The builder (engine.build) is the only writer. The reader opens the store
read-only (file:...?mode=ro), so it cannot write even by mistake.

Schema changes are numbered migrations in engine/migrations/NNNN_name.sql,
applied in order and recorded with a checksum; a store whose applied
migration no longer matches the file in this repository is refused.

A store is usable only when its state is "ready": a rebuild writes into a
temporary file, marks it ready in its last write and then renames it into
place, so a reader never sees a half-built store. open_store() refuses a
file that is not SQLite, fails the integrity check, has unknown or changed
migrations, is not ready, or was built from a different taxonomy.
"""

import hashlib
import json
import os
import re
import sqlite3
from collections import OrderedDict

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations")
_MIGRATION_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")
STATE_BUILDING = "building"
STATE_READY = "ready"

# Tables in the canonical export, with their sort keys. runs is exported
# without its two clock columns, so the same inputs always export the same.
EXPORT_TABLES = OrderedDict([
    ("meta", "key"),
    ("schema_migrations", "version"),
    ("customers", "customer_id"),
    ("ledger", "customer_id, txn_id"),
    ("features", "feature_key"),
    ("feature_buckets", "customer_id, feature_key, month"),
    ("tag_state", "customer_id, tag_id"),
    ("checkpoint_tags", "customer_id, checkpoint"),
    ("tag_history", "customer_id, checkpoint, tag_id"),
    ("runs", "run_id"),
])
EXPORT_EXCLUDED_COLUMNS = {"runs": ("started_at", "finished_at")}


class StoreError(RuntimeError):
    """The store is missing, corrupt, incomplete or built for something else."""


def migrations():
    """[(version, name, sql, checksum)] from engine/migrations, in order."""
    found = []
    for name in sorted(os.listdir(MIGRATIONS_DIR)):
        match = _MIGRATION_RE.match(name)
        if not match:
            continue
        with open(os.path.join(MIGRATIONS_DIR, name), "r", encoding="utf-8") as handle:
            sql = handle.read()
        checksum = "sha256:" + hashlib.sha256(sql.encode("utf-8")).hexdigest()
        found.append((int(match.group(1)), match.group(2), sql, checksum))
    versions = [v for v, _, _, _ in found]
    if versions != list(range(1, len(versions) + 1)):
        raise StoreError("migrations must be numbered 0001, 0002, ... without gaps")
    return found


def connect_rw(path):
    connection = sqlite3.connect(path, isolation_level=None)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def connect_ro(path):
    """A read-only connection: the database file cannot be written through it."""
    if not os.path.isfile(path):
        raise StoreError("no profile store at {}".format(path))
    uri = "file:{}?mode=ro".format(_uri_path(path))
    connection = sqlite3.connect(uri, uri=True, isolation_level=None)
    connection.execute("PRAGMA query_only = ON")
    return connection


def _uri_path(path):
    """Percent-encode the characters that would end or change a SQLite URI path."""
    text = os.path.abspath(path)
    for char, code in (("%", "%25"), ("?", "%3F"), ("#", "%23"), (" ", "%20")):
        text = text.replace(char, code)
    return text


def apply_migrations(connection):
    """Apply every migration not yet recorded; refuse a changed one. Returns
    the versions applied now."""
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL)")
    applied = {row[0]: (row[1], row[2]) for row in
               connection.execute("SELECT version, name, checksum FROM schema_migrations")}
    done = []
    for version, name, sql, checksum in migrations():
        if version in applied:
            if applied[version] != (name, checksum):
                raise StoreError("migration {:04d}_{} differs from the one this store was built with".format(
                    version, name))
            continue
        connection.execute("BEGIN IMMEDIATE")
        try:
            for statement in _statements(sql):
                connection.execute(statement)
            connection.execute("INSERT INTO schema_migrations (version, name, checksum) VALUES (?, ?, ?)",
                               (version, name, checksum))
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        done.append(version)
    unknown = sorted(set(applied) - {v for v, _, _, _ in migrations()})
    if unknown:
        raise StoreError("store has migrations this code does not know: {}".format(unknown))
    return done


def _statements(sql):
    """Split a migration into statements (no semicolons inside our SQL strings)."""
    lines = [line for line in sql.splitlines() if not line.strip().startswith("--")]
    text = "\n".join(line.split("--", 1)[0] for line in lines)
    return [s.strip() for s in text.split(";") if s.strip()]


def check_store(connection, taxonomy=None):
    """Raise StoreError unless the store is complete, consistent and (when a
    taxonomy is given) built from that taxonomy. Returns the meta dict."""
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.DatabaseError as exc:
        raise StoreError("not a readable SQLite store: {}".format(exc))
    if not result or result[0] != "ok":
        raise StoreError("integrity check failed: {}".format(result[0] if result else "no result"))
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "schema_migrations" not in tables or "meta" not in tables:
        raise StoreError("not a profile store (no migrations or meta table)")
    known = {v: (n, c) for v, n, _, c in migrations()}
    applied = {row[0]: (row[1], row[2]) for row in
               connection.execute("SELECT version, name, checksum FROM schema_migrations")}
    if applied != known:
        raise StoreError("store migrations {} do not match this code's {}".format(sorted(applied), sorted(known)))
    meta = dict(connection.execute("SELECT key, value FROM meta"))
    if meta.get("state") != STATE_READY:
        raise StoreError("store is incomplete (state {!r}): rebuild it".format(meta.get("state")))
    for key in ("as_of", "taxonomy_version", "taxonomy_hash", "history_months", "lifecycle_months"):
        if key not in meta:
            raise StoreError("store meta has no {}".format(key))
    if taxonomy is not None and meta["taxonomy_hash"] != taxonomy.content_hash:
        raise StoreError("store was built from taxonomy {} ({}), not {} ({}): rebuild it".format(
            meta["taxonomy_version"], meta["taxonomy_hash"], taxonomy.version, taxonomy.content_hash))
    return meta


def open_store(path, taxonomy=None, read_only=True):
    """Open and check a store. Read-only unless asked otherwise."""
    if not os.path.isfile(path):
        raise StoreError("no profile store at {}".format(path))
    connection = connect_ro(path) if read_only else connect_rw(path)
    try:
        check_store(connection, taxonomy)
    except Exception:
        connection.close()
        raise
    return connection


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def export(connection):
    """A canonical, deterministic dump of every table (runs without its clock
    columns): the same inputs and as-of date always give the same bytes."""
    lines = []
    for table, order in EXPORT_TABLES.items():
        columns = [row[1] for row in connection.execute("PRAGMA table_info({})".format(table))]
        keep = [c for c in columns if c not in EXPORT_EXCLUDED_COLUMNS.get(table, ())]
        query = "SELECT {} FROM {} ORDER BY {}".format(", ".join(keep), table, order)
        for row in connection.execute(query):
            lines.append(canonical({"table": table, "row": OrderedDict(zip(keep, row))}))
    return "\n".join(lines) + "\n"


def meta(connection):
    return dict(connection.execute("SELECT key, value FROM meta"))

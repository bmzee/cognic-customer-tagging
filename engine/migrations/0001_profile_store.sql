-- 0001: the profile store. Owned by the plugin; the bank's data is never written.

-- Settings and identity of the build: schema and taxonomy versions, the
-- as-of date, retention settings, and the store state ("building" until the
-- last write of a rebuild, then "ready").
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;

-- One row per customer: only the attributes rules read, plus data notes.
CREATE TABLE customers (
    customer_id       TEXT PRIMARY KEY,
    account_open_date TEXT,
    home_country      TEXT,
    home_currency     TEXT NOT NULL,
    notes             TEXT NOT NULL      -- JSON: transactions used, rows skipped by reason
) WITHOUT ROWID;

-- The transactions rules read, normalised (whole cents in the base currency,
-- canonical counterparty, restricted categories collapsed, people
-- pseudonymised). Only the months that history_months keeps.
CREATE TABLE ledger (
    customer_id       TEXT NOT NULL,
    txn_id            TEXT NOT NULL,
    posted_date       TEXT NOT NULL,
    direction         TEXT NOT NULL CHECK (direction IN ('credit', 'debit')),
    amount_cents      INTEGER NOT NULL CHECK (amount_cents > 0),
    currency          TEXT NOT NULL,
    channel           TEXT NOT NULL,
    category          TEXT NOT NULL,
    category_source   TEXT NOT NULL,
    counterparty      TEXT,
    counterparty_kind TEXT NOT NULL,
    txn_country       TEXT,
    mcc               TEXT,
    balance_cents     INTEGER,
    PRIMARY KEY (customer_id, txn_id)
) WITHOUT ROWID;
CREATE INDEX ledger_by_month ON ledger (customer_id, posted_date);

-- What each feature key means: the filters a transaction must match and
-- what is tracked about the matches.
CREATE TABLE features (
    feature_key TEXT PRIMARY KEY,
    definition  TEXT NOT NULL            -- canonical JSON
) WITHOUT ROWID;

-- Per customer, feature and calendar month: the aggregates every window is
-- answered from. Always recomputed from the month's ledger rows.
CREATE TABLE feature_buckets (
    customer_id TEXT NOT NULL,
    feature_key TEXT NOT NULL,
    month       TEXT NOT NULL,           -- YYYY-MM
    n           INTEGER NOT NULL,
    total       INTEGER NOT NULL,        -- cents
    max         INTEGER NOT NULL,        -- cents
    credit      INTEGER NOT NULL,        -- cents
    debit       INTEGER NOT NULL,        -- cents
    last_day    TEXT,
    extra       TEXT NOT NULL,           -- canonical JSON: distinct values, streams, balance
    PRIMARY KEY (customer_id, feature_key, month)
) WITHOUT ROWID;

-- The current tags at the as-of date: held tags with their reason, rule and
-- evidence; suppressed tags (lower in an exclusive group); tags that could
-- not be evaluated, with the missing fields.
CREATE TABLE tag_state (
    customer_id        TEXT NOT NULL,
    tag_id             TEXT NOT NULL,
    status             TEXT NOT NULL CHECK (status IN ('held', 'suppressed', 'not_evaluated')),
    as_of              TEXT NOT NULL,
    entered_on         TEXT,             -- first month-end check of the current run
    new_this_month     INTEGER NOT NULL DEFAULT 0,
    since_window_start INTEGER NOT NULL DEFAULT 0,
    suppressed_by      TEXT,
    reason             TEXT,
    rule               TEXT,
    evidence           TEXT,             -- JSON list of evidence items
    facts              TEXT,             -- JSON list of fact items
    missing            TEXT,             -- JSON list of missing fields
    PRIMARY KEY (customer_id, tag_id)
) WITHOUT ROWID;
CREATE INDEX tag_state_by_tag ON tag_state (tag_id, status, customer_id);

-- The tags held at each month-end checkpoint (lifecycle_months of them).
CREATE TABLE checkpoint_tags (
    customer_id TEXT NOT NULL,
    checkpoint  TEXT NOT NULL,           -- YYYY-MM-DD, a month end
    tags        TEXT NOT NULL,           -- JSON list of held tag ids, sorted
    PRIMARY KEY (customer_id, checkpoint)
) WITHOUT ROWID;

-- Entered and exited events between consecutive checkpoints.
CREATE TABLE tag_history (
    customer_id     TEXT NOT NULL,
    checkpoint      TEXT NOT NULL,
    tag_id          TEXT NOT NULL,
    event           TEXT NOT NULL CHECK (event IN ('entered', 'exited')),
    at_window_start INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (customer_id, checkpoint, tag_id)
) WITHOUT ROWID;

-- One row per builder run: what was built from what, with counts. The
-- audit trail of the store; only started_at and finished_at read a clock.
CREATE TABLE runs (
    run_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kind                TEXT NOT NULL CHECK (kind IN ('rebuild', 'follow')),
    as_of               TEXT NOT NULL,
    engine_version      TEXT NOT NULL,
    taxonomy_version    TEXT NOT NULL,
    taxonomy_hash       TEXT NOT NULL,
    input_snapshot_hash TEXT NOT NULL,
    customers           INTEGER NOT NULL,
    transactions        INTEGER NOT NULL,
    tags_held           INTEGER NOT NULL,
    notes               TEXT NOT NULL,   -- JSON: data notes, skips by reason
    started_at          TEXT NOT NULL,
    finished_at         TEXT
);

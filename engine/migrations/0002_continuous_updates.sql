-- 0002: continuous updates. Every table here is a function of the set of
-- accepted events (except late_events and feed_checkpoints, which record what
-- happened when), so an incrementally maintained store equals a batch rebuild.

-- One register per transaction id: the winning image's identity. A higher
-- version wins; at equal versions a reversal beats a posting; then the lowest
-- event id wins (the first posting, as in a batch file). A reversal that
-- arrives before its posting is kept here as a tombstone, with no ledger row.
CREATE TABLE txn_registers (
    customer_id TEXT NOT NULL,
    txn_id      TEXT NOT NULL,
    version     INTEGER NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('posted', 'reversed')),
    event_id    TEXT NOT NULL,
    posted_date TEXT NOT NULL,           -- the image's date; a tombstone's is the reversal date
    PRIMARY KEY (customer_id, txn_id)
) WITHOUT ROWID;

-- Customer attributes, versioned by the date they take effect. An evaluation
-- at a date uses the latest version effective on or before it.
CREATE TABLE customer_versions (
    customer_id       TEXT NOT NULL,
    effective_from    TEXT NOT NULL,
    version           INTEGER NOT NULL,
    event_id          TEXT NOT NULL,
    account_open_date TEXT,
    home_country      TEXT,
    home_currency     TEXT NOT NULL,
    PRIMARY KEY (customer_id, effective_from)
) WITHOUT ROWID;

-- The earliest closing date seen for each customer.
CREATE TABLE closures (
    customer_id TEXT PRIMARY KEY,
    closed_on   TEXT NOT NULL
) WITHOUT ROWID;

ALTER TABLE customers ADD COLUMN closed_on TEXT;

-- The identity of every accepted event: duplicates are skipped by id, and
-- the same id with different content is refused.
CREATE TABLE events_seen (
    event_id    TEXT PRIMARY KEY,
    digest      TEXT NOT NULL,
    type        TEXT NOT NULL,
    customer_id TEXT,
    time        TEXT
) WITHOUT ROWID;

-- Events that could not be used, with the reason (bad amount, unknown
-- currency, conflicting duplicate...). A function of each event alone.
CREATE TABLE rejected_events (
    event_id    TEXT PRIMARY KEY,
    customer_id TEXT,
    time        TEXT,
    reason      TEXT NOT NULL
) WITHOUT ROWID;

-- Events that arrived after their month was sealed (allowed lateness): kept,
-- counted and flagged, never applied; a deliberate rebuild folds them in.
CREATE TABLE late_events (
    event_id    TEXT PRIMARY KEY,
    customer_id TEXT,
    event       TEXT NOT NULL,           -- the event as received
    reason      TEXT NOT NULL,
    as_of       TEXT NOT NULL            -- the store's as-of date when it arrived
) WITHOUT ROWID;

-- Where each feed was read up to; written in the same transaction as the
-- effects of the events read, so a restart neither loses nor repeats work.
CREATE TABLE feed_checkpoints (
    feed      TEXT PRIMARY KEY,
    position  TEXT NOT NULL,
    identity  TEXT NOT NULL
) WITHOUT ROWID;

ALTER TABLE runs ADD COLUMN events_read INTEGER NOT NULL DEFAULT 0;
ALTER TABLE runs ADD COLUMN events_applied INTEGER NOT NULL DEFAULT 0;
ALTER TABLE runs ADD COLUMN events_duplicate INTEGER NOT NULL DEFAULT 0;
ALTER TABLE runs ADD COLUMN events_rejected INTEGER NOT NULL DEFAULT 0;
ALTER TABLE runs ADD COLUMN events_late INTEGER NOT NULL DEFAULT 0;

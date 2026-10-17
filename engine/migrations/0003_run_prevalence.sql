-- 0003: tag prevalence per run, for the drift report. Written with every
-- rebuild, and with every follow batch that moved the as-of date (a tick
-- re-evaluates every customer). Counts only: no customer ids and no
-- attributes of any kind, so drift is attribute-blind by construction.
CREATE TABLE run_tags (
    run_id        INTEGER NOT NULL REFERENCES runs (run_id),
    tag_id        TEXT NOT NULL,
    held          INTEGER NOT NULL,
    suppressed    INTEGER NOT NULL,
    not_evaluated INTEGER NOT NULL,
    PRIMARY KEY (run_id, tag_id)
) WITHOUT ROWID;

-- How many tags each customer holds, in five bands, at the same runs.
CREATE TABLE run_spread (
    run_id    INTEGER NOT NULL REFERENCES runs (run_id),
    band      TEXT NOT NULL CHECK (band IN ('0', '1', '2', '3', '4+')),
    customers INTEGER NOT NULL,
    PRIMARY KEY (run_id, band)
) WITHOUT ROWID;

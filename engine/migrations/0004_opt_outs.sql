-- 0004: customers who objected to profiling. An opt-out is a hard exclusion:
-- the builder deletes everything it holds about the customer and keeps only
-- the id and the earliest date of the objection, so that no later event can
-- profile them again. The plugin never lifts an opt-out by itself.
CREATE TABLE opt_outs (
    customer_id TEXT PRIMARY KEY,
    since       TEXT NOT NULL
) WITHOUT ROWID;

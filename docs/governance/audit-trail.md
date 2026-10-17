# Audit trail (template)

> **To be completed by the bank's compliance team.** What the plugin records so that any tag can be traced and any run reproduced, and what the bank must add. What applies is set by the bank's regulator and data-protection law.

## What the store records

| Record | What it holds |
| --- | --- |
| `runs` | One row per rebuild and per follow batch: kind, as-of date, engine version, taxonomy version and content hash, a hash of the input (or the feed position), customers, transactions, tags held, events read, applied, duplicate, rejected and late, data notes (including the number of opted-out customers), start and finish time |
| `run_tags`, `run_spread` | With every rebuild and every tick that moves the as-of date: per tag, how many customers hold it, are suppressed for it or cannot be evaluated for it; how many tags each customer holds. Counts only |
| `schema_migrations` | Every store migration applied, with its checksum; a changed or unknown migration is refused |
| `meta` | Store state, versions, taxonomy hash, as-of date and retention settings |
| `events_seen`, `rejected_events`, `late_events`, `feed_checkpoints` | Which events were applied (by id and digest), which were refused and why, which arrived too late, and how far each feed was read |
| `tag_state`, `checkpoint_tags`, `tag_history` | For every tag: the reason, the rule in words, each condition's value, threshold and result, and when it entered or exited |

## Reproducing a run

- `python3 -m engine.build --export --store profile.db` prints a canonical dump of the store (every table; the two clock columns of `runs` left out). The same inputs, taxonomy and as-of date always give the same bytes.
- A store maintained from a change feed equals a rebuild from the same accepted events; this is tested on every change (`tests/test_incremental.py`).
- The taxonomy's content hash covers its rules and reference tables, so a run names exactly which rules produced it.

## What the plugin does not record

- **Who asked what.** The reader is stateless and keeps no log of questions. Calls pass through Cognic's door, which is where access is logged.
- **What staff did next.** Tags never act; any action is recorded in the bank's own systems.

| Field | Entry |
| --- | --- |
| Where exports are stored for audit, and for how long | _[bank]_ |
| Access log source (Cognic's door) and retention | _[bank]_ and Cognic hosting |
| Who may run the builder | _[bank]_ |

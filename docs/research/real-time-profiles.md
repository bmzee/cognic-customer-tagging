# Real-time customer profiles

The builder keeps the profile store current from a change feed instead of rebuilding it. The question is which semantics keep that incremental store identical to a batch rebuild, whatever the order, duplication or lateness of the feed. Every tag is shown with its evidence and as-of date, so if two runs over the same events can disagree, the explanation cannot be trusted.

## Findings

### Change data capture and event-time windows

- **Log-based CDC** reads the source database's commit log. Each committed change becomes an event with before and after images, an operation code and source metadata. A connector first takes a consistent snapshot, notes the log position, then streams from that position so no change falls between the two ([Debezium PostgreSQL connector](https://debezium.io/documentation/reference/stable/connectors/postgresql.html)). After a crash it resumes from the last saved position, so recent events can arrive twice.
- **Polling** asks for rows changed since a high-water mark. It sees only current state, so intermediate versions and hard deletes are lost unless recorded.
- **Transactional outbox**: the application writes an event row in the same transaction as the business change; a relay publishes it by polling or log tailing. An event exists if and only if the change committed, but may be published twice, so consumers must be idempotent ([Transactional outbox](https://microservices.io/patterns/data/transactional-outbox.html)). Each row has a unique event id for deduplication, and the aggregate id becomes the message key, preserving per-entity order ([Outbox Event Router](https://debezium.io/documentation/reference/stable/transformations/outbox-event-router.html)).
- None gives a global order: at best order per key, with at-least-once delivery by default ([Kafka delivery guarantees](https://docs.confluent.io/kafka/design/delivery-semantics.html)).
- **Event time vs processing time.** Group by when something happened, not when it arrived. A watermark is the system's estimate that event time has reached a point. It is a heuristic: if it runs ahead, some data arrives late; if it lags, results wait. Batch is the special case where the watermark jumps to the end once all input is read ([The Dataflow Model](https://www.vldb.org/pvldb/vol8/p1792-Akidau.pdf)).
- **Windows and lateness.** Tumbling windows are fixed-length, non-overlapping and aligned to the epoch. Window state is kept until the watermark passes the window end plus the allowed lateness; later elements are dropped by default or sent to a side output ([Flink windows](https://nightlies.apache.org/flink/flink-docs-stable/docs/dev/datastream/operators/windows/)). Calendar months are not fixed-length, so a month bucket key has to come from the event's date, not from a fixed window size.

### Incremental aggregates

- **Invertible aggregates** (count, sum, and mean as a sum and count pair) update by a delta, and a removal is a subtraction. With a signed weight on each row, count and sum are linear, so each is its own incremental form ([DBSP](https://arxiv.org/abs/2203.16684)).
- **Non-invertible aggregates** (max, min, distinct count) cannot absorb a removal: removing the current maximum needs the remaining values. DBSP maintains them by recomputing the whole group ([DBSP](https://arxiv.org/abs/2203.16684)). The sliding-window literature classifies max and min as associative but not invertible ([In-order sliding-window aggregation](https://arxiv.org/abs/2009.13768)).
- **Standard remedies:**
  - Recompute the affected group from retained rows. Cost is bounded by group size.
  - Keep a value-to-count map per group, which makes max, min and distinct invertible at the cost of storing it.
  - For in-order sliding windows, the two-stacks family gives constant amortized or worst-case cost for any associative operator, but only for first-in-first-out streams ([In-order sliding-window aggregation](https://arxiv.org/abs/2009.13768)).
  - Pre-aggregated buckets combined at read time. Merging buckets needs only associativity; retracting a row inside one still needs invertibility or a recompute.

### Late events, duplicates, corrections and restart

- **Retract vs upsert.** A retract stream encodes an update as a removal of the old row followed by an addition of the new one. An upsert stream needs a unique key and sends one message per update, which is cheaper ([Flink dynamic tables](https://nightlies.apache.org/flink/flink-docs-release-2.3/docs/concepts/sql-table-concepts/dynamic_tables/)). The Dataflow model adds a third refinement mode, accumulating and retracting, for consumers that regroup earlier results ([The Dataflow Model](https://www.vldb.org/pvldb/vol8/p1792-Akidau.pdf)).
- **Compensating events** leave old results alone and book an offsetting change in the current period: fine for sums, meaningless for max or distinct.
- **Idempotency.** A primary key on the output makes repeated deliveries harmless ([Kafka delivery guarantees](https://docs.confluent.io/kafka/design/delivery-semantics.html)). SQLite's `ON CONFLICT DO NOTHING` and `DO UPDATE` need version 3.24 or later ([SQLite UPSERT](https://www.sqlite.org/lang_upsert.html)).
- **Exactly-once effect.** Save the consumer position in the same transaction as the output. Saving it before risks loss; after risks reprocessing ([Kafka delivery guarantees](https://docs.confluent.io/kafka/design/delivery-semantics.html)).
- **SQLite specifics.** In WAL mode readers do not block the single writer, and each read transaction sees a fixed snapshot. With `synchronous=NORMAL` the last commits can roll back after power loss. A read-only connection needs the `-wal` and `-shm` files to exist or a writable directory, and a database must never be separated from its WAL file ([SQLite WAL](https://www.sqlite.org/wal.html)). Without `AUTOINCREMENT`, ids of deleted rows can be reused; with it, ids only increase ([SQLite autoincrement](https://www.sqlite.org/autoinc.html)).

### Feature-store patterns

- **Offline vs online.** The offline store holds history for building training sets; the online store holds the latest value per key. A point-in-time join takes, for each entity and timestamp, the latest value at or before that timestamp, so nothing from the future leaks in ([Feast point-in-time joins](https://docs.feast.dev/getting-started/concepts/point-in-time-joins)).
- **Training/serving skew** comes from two code paths treating the same data differently, or from data changing between computation and use. Remedies: share code between the paths and log what was served ([Rules of Machine Learning](https://developers.google.com/machine-learning/guides/rules-of-ml)).
- **One definition, two executions.** Keeping separate batch and streaming implementations in agreement is persistently painful. The alternative is one codebase: replay the retained log into a new output table, then switch readers to it ([Questioning the Lambda Architecture](https://www.oreilly.com/radar/questioning-the-lambda-architecture/)).
- **Property-based testing** generates random sequences of actions, checks invariants after each step, and reduces a failure to a short reproducing sequence ([Hypothesis stateful tests](https://hypothesis.readthedocs.io/en/latest/stateful.html)).
- Here the profile store is the online side and a batch rebuild from the ledger the offline side. The skew to fear is a tag whose evidence a rebuild cannot reproduce.

## Design decisions for this plugin

1. **Event envelope.** Every event carries `event_id`, `type`, `schema_version`, an entity key, a source-assigned `version` increasing per entity (log position or outbox sequence), a business `event_date`, `recorded_at` and the full after-image. Reversals and corrections carry the whole target transaction, including its booking date, never a diff.
2. **Set semantics.** The store is a pure function of the set of accepted events and the as-of date when four rules hold:
   - `applied_events(event_id PRIMARY KEY)` with `ON CONFLICT DO NOTHING` turns the delivered multiset into a set, and runs before the lateness check. The same id with a different content hash is a feed defect: the batch rolls back and the run stops.
   - Each transaction is a register keyed by transaction id. The winning image has the highest `(version, event_id)` from the event, never from arrival order. A maximum is commutative, associative and idempotent, so order cannot matter.
   - A reversal is an image with status reversed and a higher version. It contributes zero and wins even if it arrives before the original.
   - `as_of` is the maximum `clock.tick` date seen. A duplicate or older tick changes nothing.
3. **Lateness.** The cut-off is `as_of - L` days, with `L` configured (for example 3) and recorded on every run. A month is sealed once its last day is on or before the cut-off. An event is late if its effective date falls in a sealed month (for a reversal or correction, the original booking date counts too). Late events go to `late_events` with a reason, are counted in `runs`, and are flagged in the customer's evidence; they change nothing else until a deliberate rebuild. This gate is the one step that depends on arrival order, which is why the equality property below covers deliveries within the bound.
4. **Live tags, sealed history.** Current tags read every month up to the as-of date, including the open month, so a profile is fresh the day an event arrives. History (`entered`/`exited`) is recorded at month-end checkpoints, and a checkpoint is final once its month is sealed. An event within the bound recomputes the affected customer's current tags and any unsealed checkpoint, so history stays reproducible without delaying tags by `L` days.
5. **Buckets.** Every bucket of an affected `(customer, month)` is recomputed from that month's ledger rows: count and sum could change by delta, but max, min, distinct sets and recurring-stream statistics cannot, and one recompute path for batch and incremental leaves nothing to drift. A correction that changes month recomputes both months.
6. **Atomic checkpoint.** Open with `isolation_level=None` (Python 3.9 has no `autocommit` attribute), then per batch:

   ```sql
   BEGIN IMMEDIATE;
   INSERT INTO applied_events(...) VALUES (...) ON CONFLICT(event_id) DO NOTHING;
   -- ledger, buckets, tags, history for affected keys only
   UPDATE feed_offsets SET position = ?, file_identity = ? WHERE feed = ?;
   COMMIT;
   ```

   Offset and effects commit or roll back together, so `synchronous=NORMAL` in WAL mode is safe: a lost commit is simply replayed. Refuse to start if `sqlite3.sqlite_version` is below 3.24.
7. **JSONL follower.** The position is the byte offset after the last newline-terminated line; a partial trailing line waits for the next poll. Store a file identity (device, inode, hash of the first line); if it changes or the file shrinks, restart from zero and let deduplication absorb repeats.
8. **Outbox poller.** The outbox uses `INTEGER PRIMARY KEY AUTOINCREMENT`; the position is the last id applied. With concurrent writers a lower id can commit later, so re-read a window below the position. Prune rows only below the committed position.
9. **Read-only tool server.** Open with `file:<path>?mode=ro` and `uri=True`. Each answer uses one read transaction, hence one snapshot.
10. **Rebuilds.** Batch rebuild and builder call the same rule and aggregate functions. A rebuild writes a new store file, checkpoints and closes it, then switches a small pointer file to it; nothing is renamed over a live WAL-mode database. Scheduled reconciliation rebuilds into a scratch file and diffs it with the live store.
11. **Equality property, standard library only.** With `random.Random(seed)`, generate transactions across month and year boundaries, corrections that change month, reversals delivered before their originals, attribute changes and ticks. Deliver each event before it would become late, duplicate about one in ten, split into random batches, and abandon some batches mid-transaction to simulate a crash. Assert:
    - a sorted dump of ledger, buckets, tag state, evidence and history equals a batch rebuild at the final as-of; `runs` and processing timestamps are excluded;
    - events delivered after their seal appear in `late_events`, and the rest equals a rebuild without them;
    - replaying the whole feed again changes nothing.

    On failure, print the seed, shrink the event list while the failure persists, and keep the seed as a regression case.

## What we adopt, what we reject, and why

- **Adopt:** dedupe by event id plus last-writer-wins by `(version, event_id)`. Together they make the result independent of order and duplication.
- **Adopt:** full after-images and upsert semantics for corrections and reversals. A diff is unsafe when it arrives before its base.
- **Adopt:** an as-of date driven only by `clock.tick`. Wall-clock time would make runs unrepeatable.
- **Adopt:** a lateness bound with a quarantine table instead of a silent drop. An auditable store must show what it did not apply.
- **Adopt:** sealed months for history, with live data for current tags. History is rebuildable and final once sealed, and tags are still fresh on the day an event arrives.
- **Adopt:** offset and effects in one SQLite transaction, for exactly-once effect without a broker.
- **Adopt:** one set of rule functions for batch and incremental paths, plus scheduled reconciliation. Two implementations would drift.
- **Reject:** gating lateness on the event's own `recorded_at`. Admission would then be a set function, but a relay outage longer than `L` could rewrite sealed months and history.
- **Reject:** compensating events for late corrections. They fail for max, min and distinct, and double count when the original never arrived.
- **Reject:** value-to-count maps for non-invertible aggregates, for now. A customer-month is small, so recomputing it from the ledger is simpler.
- **Reject:** two-stacks and similar sliding-window structures. They assume first-in-first-out input; our calendar-month buckets are fed out of order.
- **Reject:** a property-testing library as a dependency. CI stays dependency-free, so a seeded generator and a small shrink loop follow the same pattern.

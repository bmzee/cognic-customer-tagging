# Retention (template)

> **To be completed by the bank's compliance team.** What the plugin keeps and for how long by design, and the periods only the bank can set. What applies is set by the bank's regulator and data-protection law.

| Record | Kept by the plugin | Why | Bank decision |
| --- | --- | --- | --- |
| Transactions in the profile store (`ledger`, `txn_registers`) | 13 + 6 calendar months back from the as-of month (`history_months` + `lifecycle_months`); older rows are deleted after every tick | The longest rule window is 13 months; 6 more let the oldest month-end check see a full window | _[bank]_ confirm |
| Customer attributes and closures (`customers`, `customer_versions`, `closures`) | While the customer is in the bank's data; attribute versions older than the window are dropped once a newer one applies | Tenure, "abroad or not" and closures | _[bank]_ confirm |
| Monthly aggregates (`feature_buckets`) | The same window | Recomputed from the ledger | – |
| Tags, checkpoints and history (`tag_state`, `checkpoint_tags`, `tag_history`) | The current tags, and the last 6 month-end checks | Lifecycle and "since when" | _[bank]_ confirm |
| Event ids and digests (`events_seen`), rejected events (`rejected_events`) | The same window | Idempotency and data-quality notes | – |
| Late events (`late_events`) | Until the store is rebuilt | Kept aside for review, never applied | _[bank]_ review and clearing |
| Opt-outs (`opt_outs`: customer id and date) | As long as the objection stands | So a later event cannot profile the customer again | _[bank]_ |
| Runs (`runs`, `run_tags`, `run_spread`) | Not deleted by the plugin; counts only, no customer data | The audit trail and the drift report | _[bank]_ |
| Old stores and exports | Not kept by the plugin; a rebuild replaces the store | Each export is reproducible from the same inputs | _[bank]_ (Q23) |
| The plugin's image | Holds only synthetic fixture data | – | – |

Changing `history_months` or `lifecycle_months` is a taxonomy change (see [taxonomy-change-control.md](taxonomy-change-control.md)): it changes the content hash and needs a rebuild.

| Field | Entry |
| --- | --- |
| Retention schedule reference | _[bank]_ |
| Who reviews late events and how often | _[bank]_ |
| How long store copies kept for audit are held | _[bank]_ |

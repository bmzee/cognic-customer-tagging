# Customer rights (template)

> **To be completed by the bank's compliance team.** How the plugin supports a customer's rights, and what the bank must decide. What applies is set by the bank's regulator and data-protection law.

## Explanation

A customer may ask why they are treated a certain way, or which tags apply to them. Staff can answer from the tools, never from guesswork:

- `get_customer_tags` gives every tag the customer holds with its reason, the rule in words, each condition's value, threshold and result, the as-of date and when the tag started.
- `explain_tag` says why one tag does or does not apply: the unmet conditions with the customer's values, the missing data, or the tag that took priority.
- `customer_tag_history` gives the tags held at each month-end check and when each entered or exited.

Every answer describes behaviour recorded up to the as-of date. A tag is never a judgement about the person, and no tag triggers a decision on its own.

| Field | Entry |
| --- | --- |
| Who may give a customer an explanation | _[bank]_ |
| How a request is logged | _[bank]_ |
| Wording for customers | _[bank]_ |

## Objection and opt-out

**What the plugin does.** An opt-out is a hard exclusion, honoured by the builder in every run:

- **How the bank records it.** Either a `profiling_opt_out` column in the customer file (`true`, `yes`, `y` or `1`), or `"profiling_opt_out": "true"` in a `customer.updated` event. Any other non-empty value also counts as an opt-out: when in doubt the plugin stops profiling.
- **What happens.** The customer's transactions, buckets, tags, checkpoints, history, event records and data notes are deleted from the store. Only the customer id and the date of the objection are kept (`opt_outs`), so that a later event cannot profile them again. Every later event for that customer is dropped without being stored.
- **The date kept.** For an objection in a change feed, the event's date (the earliest, if there are several). A customer file carries no date, so an objection taken from it is recorded with the placeholder date `1900-01-01`, the date from which attributes in a customer file take effect.
- **When.** At once, in the batch that carries the objection, whatever its date: allowed lateness never delays an opt-out.
- **What staff see.** No profile: the reader answers as for an unknown customer, and the customer appears in no list or count. The print-only engine (`python3 -m engine --customer ...`) reports the id as unknown.
- **Where it is recorded.** In each run's notes (`runs.notes`, `opted_out`): for a rebuild, how many customers in the store have opted out; for a follow batch, how many events in that batch were objections or were dropped because the customer had opted out.
- **Tested.** `tests/test_opt_out.py`: a rebuild never stores an opted-out customer (its profile tables equal those of a store built as if the customer never existed); following removes everything at once and drops later events; an objection beyond the allowed lateness is still honoured; the print-only engine skips the customer. `tests/test_incremental.py`: the followed store still equals a batch rebuild when an objection arrives mid-stream.

**Withdrawing an objection.** The plugin never lifts an opt-out by itself. If a customer withdraws it, the bank removes the flag from its records and rebuilds the store from data that no longer carries the objection: a fresh customer file without the flag, or an event history from which the bridge has left the objection out. A rebuild from a history that still holds the objection applies it again. Profiling then restarts from the data the bank provides.

| Field | Entry |
| --- | --- |
| Basis for profiling, and whether objection is absolute | _[bank]_ (an objection to profiling for direct marketing is commonly absolute) |
| Channels for objecting | _[bank]_ |
| Time to record an objection in the bank's records | _[bank]_ |
| Who confirms to the customer | _[bank]_ |

## Access and correction

- **Access.** The tags and their evidence come from the tools above; the underlying transactions are the bank's own records.
- **Correction.** The plugin never edits data. A wrong attribute or transaction is corrected in the bank's systems; the correction reaches the store as an event (or in the next rebuild) and the affected tags are recomputed.
- **Erasure.** Deleting a customer from the bank's records and rebuilding removes them; an opt-out removes them at once.

| Field | Entry |
| --- | --- |
| How access requests include tags | _[bank]_ |
| Erasure process and timing | _[bank]_ |

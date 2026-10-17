# Customer tagging: later stages

Stage 1, this repository, is content and logic only: the tag taxonomy, the rules engine, synthetic data, tests and a draft safety file. Nothing runs inside Cognic yet. The later stages reuse `taxonomy/tags.json` and `engine/` unchanged. What changes is where the data comes from, when the engine runs and where results are kept.

## Stage 2: scheduled runs against a read-only copy

- **Plugin tool server.** The engine is packaged as a plugin tool server in a pinned container image with network access denied. It offers read tools such as `tag_customers`, which tags a batch and returns tags with evidence, and `explain_customer`, which explains one customer's tags or why a tag does not apply. Each tool has strict input and output schemas, the reader tier and the read effect. The structured output contract belongs here, not on the stage 1 skill.
- **Read-only data copy.** The server reads a read-only copy of customer and transaction data, never the system of record, through a read credential that the bank's administrator binds. Mapping the bank's columns to the data contract is reviewed configuration, and protected-trait columns are never mapped.
- **Schedule.** A scheduled run, for example nightly or after month end, tags every customer as of a fixed date. Runs are deterministic: the same copy, taxonomy version and as-of date always give the same result, so any run can be reproduced for audit.
- **Profile store.** Results go to a profile store: customer id, tag id, as-of date, taxonomy and engine versions, the reason, the evidence, and when the tag was first and last seen. History is kept for audit for a period the bank sets. Writing the store changes shared state, so it needs its own reviewed write path with consent, separate from the read tools. The safety file then gains the server, its tools and the extra effects they need.
- **Change control.** `tags.json` is versioned. A threshold change goes through the bank's policy owners together with a preview of which customers' tags it would change.

## Stage 3: real-time profiles

- **Change feed.** A change feed from the bank, carrying new transactions and account changes, replaces the nightly batch as the trigger.
- **Watchers and standing goals.** Cognic's planned watchers follow the feed. A standing goal such as "keep customer profiles current" re-evaluates only the customers whose data changed.
- **Incremental, deterministic evaluation.** Each event re-evaluates the affected customer's windows. Events are idempotent by transaction id, and late or out-of-order events simply re-evaluate the windows they fall in. Time alone also changes tags such as dormant, so a daily tick moves the as-of date.
- **Tag changes as events.** Gaining or losing a tag is recorded with its evidence and can notify the owning team. A periodic full run reconciles any drift against a batch result.
- **Protecting source systems.** Batching and rate limits keep the feed from loading the bank's core systems.

## Compliance review needed before real data

Profiling customers needs a review before stage 2 reads real data:

- **Lawful basis and purpose.** Which teams may use tags and for what, such as service and product fit. Tags must not drive automated decisions with legal or similarly significant effects without human review.
- **Data protection impact assessment.** Under the applicable data protection law and the regulator's rules, with records of processing and a retention period.
- **Transparency and customer rights.** Customers can learn which tags apply and why, object, and have errors corrected. The reason and evidence on every tag make this practical.
- **Fairness testing.** Disparate-impact checks on held-out data in a controlled environment, which is the only place protected attributes may be used, never the engine. Each tag is reviewed for proxy effects, for example remittance or branch use correlating with national origin or age, and tags that fail are redesigned or dropped.
- **Age.** Excluded by default. Any use needs an explicit, recorded bank-policy decision in the taxonomy and an engine change.
- **Model governance.** The taxonomy is governed like a model, with an owner, validation, approved thresholds, versioning and monitoring of tag rates over time.
- **Access and audit.** Tags and evidence are confidential personal data: role-based access, a log of who viewed what, and no export outside approved paths.
- **Human oversight.** Tags inform staff. They are never the only basis for a decision about a customer.

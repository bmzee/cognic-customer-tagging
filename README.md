# Cognic customer tagging

A plugin for Cognic that tags customers from their transactions and balances, keeps a live profile per customer and explains every tag with the rule and the evidence that produced it. It is built and proven here on synthetic data, and installed into Cognic once Cognic's plugin hosting is ready.

**Status:** the full build runs as a stack of draft pull requests, one per phase; `docs/STATUS.md` has one row per phase. Built so far:
- a taxonomy of 54 behaviour-based tags in 10 groups, with a version and a content hash (`taxonomy/tags.json`), plus a counterparty normalisation table and a merchant code table;
- a deterministic rules engine (`engine/`) that evaluates tags from per-month feature buckets, with tag lifecycle at month-end checkpoints;
- seeded synthetic data with expected tags for 62 labelled scenarios (`data/`), and tests (`tests/`);
- one generated card per tag (`docs/tags/`);
- research notes and the target design ([DESIGN.md](DESIGN.md), `docs/research/`).

## What it does

The engine reads `customers.csv` and `transactions.csv` and applies the rules in `taxonomy/tags.json`. For each customer it returns the tags whose rules were met. Each tag comes with:

- a **reason** in plain words, for example "salary credited monthly, 6 of last 6 months, about 3,000.00 USD a month";
- the **rule**, for example "months with a salary credit, in the last 6 complete months: at least 6";
- the **evidence**: every number the rule looked at, its threshold, the dates it covered and the months that counted;
- its **lifecycle**: `entered_on`, the first month-end check of the current run at which the tag held, or "new this month" when it started after the last month end.

A tag whose rule needs a missing field, such as an account opening date or a balance, is reported as "not evaluated" with the missing field. It is never guessed. Lifecycle stages (new, active, going dormant, dormant, re-engaged) form one exclusive group: the first that holds wins, and the others are reported as suppressed.

## Layout

| Path | What it is |
| --- | --- |
| `.claude-plugin/plugin.json` | Claude Code plugin manifest |
| `skills/customer-tagging/`, `skills/segment-explorer/`, `skills/tag-review/` | Instructions: explain a customer's tags; find customers by tag with care; review the taxonomy |
| `commands/tag-customers.md`, `commands/explain-customer.md`, `commands/tag-report.md` | `/tag-customers`, `/explain-customer`, `/tag-report` |
| `agents/customer-profiler.md` | The reader-tier agent: the reader's tools, the skills, and an explicit output schema |
| `cognic.plugin.json` | Draft Cognic safety file |
| `taxonomy/tags.json` | The tags: groups, fields, rules, thresholds, windows, reasons, polarity, limitations, version, hash and changelog |
| `taxonomy/counterparties.json`, `taxonomy/merchant_codes.json` | Counterparty normalisation and ISO 18245-style merchant codes (synthetic) |
| `engine/` | The rules engine, Python standard library only |
| `engine/cards.py` | Generates the tag cards in `docs/tags/` |
| `engine/build.py`, `engine/profile.py`, `engine/store.py` | The builder, how a customer's profile rows are written, and the SQLite profile store |
| `engine/migrations/` | Numbered store migrations, applied in order and checked by checksum |
| `engine/events.py`, `engine/feeds.py`, `engine/incremental.py` | The event model and CSV-to-events conversion, the JSONL and SQLite-outbox feed adapters, and continuous updates with the batch rebuild they always equal |
| `server/`, `bin/profile-reader`, `.mcp.json` | The reader: a read-only MCP tool server over stdio, its entry point in the image, and its one stdio declaration |
| `Containerfile`, `.dockerignore`, `.github/workflows/image.yml`, `tools/smoke.py`, `tools/image_digest.py` | The reader's image (built in CI only), its reproducibility check and the smoke test |
| `evals/scenarios.json`, `evals/README.md` | 54 evaluation scenarios (staff question, expected tool calls, facts the answer must contain, phrases it must not, refusals) and their format |
| `tools/fairness.py`, `.github/workflows/fairness.yml`, `docs/fairness-report.md` | The fairness kit on synthetic attributes (tests and a report only, never in the engine or the reader), its full-size CI run, and the report |
| `tools/drift.py`, `docs/drift-report.md` | Tag-prevalence drift from the runs a store records, and an example report |
| `docs/governance/` | Templates for the bank's compliance team: a DPIA-style assessment, customer rights (with the opt-out the builder honours), retention, the audit trail and taxonomy change control |
| `tools/bench.py`, `.github/workflows/benchmark.yml` | Scale benchmarks: a dense synthetic generator, rebuild time and continuous-update latency (large runs in CI only) |
| `data/generate.py` | Seeded synthetic data generator |
| `data/*.csv`, `data/expected_tags.json` | Generated data and the labelled scenarios' expected tags |
| `tests/` | `unittest` suite; latest results in `tests/RESULTS.md` |
| `tools/validate_safety_file.py` | Standard-library validator for the safety file |
| `.github/workflows/tests.yml` | CI: runs the tests on Python 3.9 to 3.13 |
| `docs/tags/` | One generated card per tag, and an index |
| `docs/STATUS.md`, `docs/OPEN-QUESTIONS.md` | Build status per phase, and the questions only Cognic's hosting can settle |
| `DESIGN.md` | Target architecture: builder, profile store, reader tool server, skills and agent; why incremental equals batch; decisions from the research |
| `docs/research/` | Research notes on the plan's eight topics, the MCP specification, the skill format and evaluation, each ending with what we adopt and reject, and `SOURCES.md` |

## Running it

Python 3.9 or later, standard library only. Run from the repository root.

Explain one customer in plain text, writing nothing:

```bash
python3 -m engine --customers data/customers.csv --transactions data/transactions.csv --customer C0003 --format text
```

Explain why one tag does or does not apply:

```bash
python3 -m engine --customers data/customers.csv --transactions data/transactions.csv --customer C0002 --why salary-earner --format text
```

Tag everyone and write `tagged.json` and `tagged.csv` into a folder:

```bash
python3 -m engine --customers data/customers.csv --transactions data/transactions.csv --out-dir out
```

List every tag with its rule:

```bash
python3 -m engine --list-tags
```

Print the content hash of the taxonomy and its reference tables (a rule change needs a new version, this hash and a changelog entry in `tags.json`):

```bash
python3 -m engine --taxonomy-hash
```

Regenerate the tag cards after a taxonomy change (a test fails while they are stale):

```bash
python3 -m engine.cards --out docs/tags
```

Other options: `--as-of YYYY-MM-DD` tags as of a past date; the default is the latest transaction date in the file, never today's date. `--include-unmet` also lists the tags that did not apply, with their evidence.

Build the profile store from the data copy (the only writer; the file appears only when complete):

```bash
python3 -m engine.build --rebuild --customers data/customers.csv --transactions data/transactions.csv --store out/profile.db
```

Apply new events from a change feed (a JSONL file or a SQLite outbox), everything available, then exit:

```bash
python3 -m engine.build --follow --store out/profile.db --jsonl feed.jsonl
```

Print a canonical dump of the store; the same inputs and as-of date always give the same bytes:

```bash
python3 -m engine.build --export --store out/profile.db
```

Regenerate the synthetic data, which gives byte-identical files for the same seed:

```bash
python3 data/generate.py
```

Run the tests:

```bash
python3 -m unittest discover -s tests -t .
```

CI runs the same command on Python 3.9 to 3.13 on every push and pull request (`.github/workflows/tests.yml`). The draft safety-file schema is private and stays out of this repository and its CI, so CI skips that one test; run it locally with `COGNIC_SAFETY_SCHEMA` set (see `docs/OPEN-QUESTIONS.md`, Q1).

## Profile store

`python3 -m engine.build --rebuild` writes one SQLite file owned by the plugin. It never writes the bank's data and refuses to write over an input. The store holds:

| Table | What it holds |
| --- | --- |
| `meta` | Store state (`building` until the last write, then `ready`), engine and taxonomy versions, taxonomy hash, as-of date, retention settings |
| `customers` | The attributes rules read, and per-customer data notes |
| `ledger` | Normalised transactions inside the retention window |
| `features`, `feature_buckets` | What each feature means, and its aggregates per customer and calendar month, always recomputed from the ledger |
| `tag_state` | Held tags with reason, rule, evidence and `entered_on`; suppressed tags; not-evaluated tags with the missing fields |
| `checkpoint_tags`, `tag_history` | Tags held at each month-end checkpoint, and the entered and exited events between them |
| `runs` | One row per builder run: as-of date, versions, taxonomy hash, input snapshot hash, counts, start and finish |
| `opt_outs` | Customers who objected to profiling: only the id and the earliest date of the objection |
| `run_tags`, `run_spread` | For every rebuild and every tick that moves the as-of date: per tag, how many customers hold it, are suppressed for it or cannot be evaluated for it, and how many tags each customer holds (counts only; read by the drift report) |

**Retention.** The store keeps `history_months` (13) plus `lifecycle_months` (6) calendar months back from the as-of month. `history_months` covers the longest rule window, and the extra months let the oldest month-end checkpoint see a full window, so the store's history equals a batch run's. Nothing older is kept: tags need nothing older, and data minimisation forbids keeping it.

**Safety.** A rebuild writes into a temporary file and renames it into place only when complete. `engine.store.open_store` refuses a file that is not SQLite or fails the integrity check, has unknown or changed migrations, is not marked ready, or was built from a different taxonomy hash. Readers open the store with `file:...?mode=ro`, so they cannot write.

## Continuous updates

Everything the builder reads is a versioned JSON event (`customer-tagging.event/1`): `transaction.posted`, `transaction.reversed`, `transaction.corrected` (a full after-image), `customer.updated` (a full after-image, effective from its date), `account.closed`, and `clock.tick`, the end of a day, which moves the as-of date so time-based tags such as "going dormant" change with no new transaction. `engine/events.py` documents every field and how a bank's change data capture maps onto them. The CSV copy is turned into the same events, so a CSV rebuild and a feed are one path.

`--follow` reads a JSONL file (position: the byte offset after the last complete line, plus the file's identity) or polls a SQLite outbox table (position: the last sequence number), in batches. Each batch is one SQLite transaction holding all its effects and the feed position, so a crash loses nothing and repeats nothing. It depends on no message broker.

- **Idempotent:** an event id seen before is skipped; the same id with different content is refused.
- **Order-independent:** each transaction is a register won by the highest version, then a reversal over a posting, then the lowest event id; customer attributes are versioned by effective date. A reversal or correction that arrives before its posting is handled.
- **Incremental:** an event recomputes only its customer's affected month buckets and re-evaluates only that customer, at the as-of date and at the checkpoints on or after its effective date.
- **Allowed lateness:** a month is sealed once it ended more than `--lateness-days` (default 3) before the as-of date; an event dated in a sealed month is kept in `late_events`, counted and not applied, and a rebuild folds it in.

The property that proves it: for any seeded random order of the same events, with duplicates, late arrivals within the bound, restarts and crashes, the followed store equals a batch rebuild of the same events (`tests/test_incremental.py`; CI runs 40 short and 4 long seeds on every push).

## The reader (read-only tool server)

`python3 -m server --store profile.db` (in the image: `/app/profile-reader --store /data/profile.db`) answers staff questions through six tools, over stdio, standard library only:

| Tool | Input | What it returns |
| --- | --- | --- |
| `list_tags` | optional `group` | Every tag's rule in words, the data it reads, polarity, limitations, exclusive group, and the intended and prohibited uses |
| `get_customer_tags` | `customer_id` | The customer's current tags, each with reason, rule, every condition's evidence, `entered_on` and the as-of date; suppressed and not-evaluated tags; data notes |
| `explain_tag` | `customer_id`, `tag_id` | Why a tag does or does not apply: the rule and every condition's value, threshold and result, the unmet conditions, missing data or the tag that took priority |
| `find_customers_by_tag` | `tag_id`, optional `page`, `page_size` (at most 50) | Customer ids and display names only, one page at a time |
| `tag_summary` | optional `group` | Per tag: how many hold it, are suppressed, cannot be evaluated, and the share holding it |
| `customer_tag_history` | `customer_id` | The tags held at each month-end check, and when each entered or exited |

- **Strict schemas.** Every input and output schema is a closed object with bounded strings and arrays, in the vocabulary Cognic's safety file accepts. Extra or mistyped arguments are refused as tool errors, and an output that breaks its own schema is never sent.
- **Read-only.** Each call opens the store with `file:...?mode=ro` and `query_only`, checks it, answers and closes it. There is no network, no credential and no write path; a test refuses network, process or write-SQL code in `server/`.
- **Limits.** Messages up to 64 KiB, arguments up to 4 KiB, pages of at most 50, a SQLite work budget per call and a 10-second time limit.
- **Protocol.** JSON-RPC 2.0 over newline-delimited stdio. Modern stateless requests (protocol 2026-07-28: version and capabilities in each request's `_meta`, `server/discover`) and legacy clients that open with `initialize` (2025-11-25, 2025-06-18, 2025-03-26) are both served; see `docs/research/mcp-protocol.md`.
- **No names.** The store holds no names, so `display_name` is a label for the record ("Customer C0042"), never the person's name (`docs/OPEN-QUESTIONS.md`, Q28).

## The image

`Containerfile` builds the reader's image, in CI only (`.github/workflows/image.yml`); images are never built on a shared machine.

- **Base:** `python:3.12-slim`, pinned by its multi-architecture index digest.
- **Contents:** the code (`engine/`, `server/`), the taxonomy and a read-only synthetic fixture store compiled in a build stage from `data/`, at `/data/profile.db`. Nothing else: no tests, docs, CSV files or safety file.
- **Runtime:** no package is installed at build or run time; the user is uid 10001; the entry point is `/app/profile-reader --store /data/profile.db`, exactly the command the safety file pins.
- **Reproducible:** `SOURCE_DATE_EPOCH` fixes every timestamp (the builder's run clock included) and BuildKit rewrites layer timestamps, so two builds of a commit give the same manifest digest. CI builds twice and fails if they differ, and compares the digest with the one pinned in `cognic.plugin.json`.
- **Smoke test:** CI runs the server in the image with `--network none --read-only --cap-drop ALL`, initialises, lists the tools (their digest must equal the safety file's `toolListDigest`), calls every tool once and validates each result, and checks the container cannot write its store. The same `tools/smoke.py` runs against a local reader in the test suite.

In production the bank's store is mounted read-only at `/data/profile.db` over the fixture (`docs/OPEN-QUESTIONS.md`, Q29). Where the image is published is an operator decision (Q31).

## Data contract

`customers.csv` needs `customer_id`. The engine also reads `account_open_date` for tenure rules, `home_country` for "abroad" rules, `home_currency`, which defaults to the base currency, and the optional `profiling_opt_out`. It reads no other column. Names, account numbers and any protected-trait column are ignored and never loaded.

**Opt-out.** A customer whose `profiling_opt_out` is set (anything but empty, `false`, `no`, `n` or `0`; when in doubt the plugin stops profiling) is never tagged. In a change feed the same flag in a `customer.updated` event is an objection: the builder deletes everything it holds about the customer at once, whatever the event's date, keeps only the id and the date in `opt_outs`, and drops the customer's later events. The reader then has no profile for them. See `docs/governance/customer-rights.md`.

`transactions.csv` needs `customer_id`, `posted_date` and `amount`. It may also have `txn_id`, `currency`, `direction`, `channel`, `category`, `counterparty`, `txn_country`, `mcc` (a four-digit merchant category code) and `balance_after` (the balance after the transaction, in the home currency).

- **Signs.** With a `direction` of credit or debit, the amount may be unsigned, or signed with money out negative. Without a direction, a negative amount is a debit and a positive amount a credit. A negative credit is a contradiction and is skipped.
- **Currency.** Amounts are converted to the base currency with the fixed rate table in `tags.json` and kept as whole cents. An empty currency means the customer's home currency. An unknown currency is skipped, never guessed.
- **Categories.** The bank's own category wins. When it is empty, the merchant code table fills it in; otherwise it is "uncategorized". Health, worship, charity, childcare, schooling and pension categories are collapsed into one opaque `restricted` category when a row is read, so they are never stored, and no rule may select it.
- **Counterparties.** A raw counterparty is cleaned and mapped with `taxonomy/counterparties.json` to a canonical name and a kind (employer, business, person, merchant, biller, financial, own account, unknown), so "SYN STREAMCO*0412" and "SYN-STREAMCO" are one merchant. A person is kept only as a pseudonymous token.
- **Balances.** Rules that read the balance need `balance_after`; without it they are "not evaluated". A month with no transaction carries the previous closing balance.
- **Bad rows.** Rows with a bad date, amount, direction or balance, a zero amount, an unknown customer or a duplicate `txn_id` are skipped. Every skip is counted by reason in the output's data notes.
- **Time windows.** Day windows end on the as-of date. Month windows use complete calendar months, so a mid-month as-of date does not count the partial month.

The generated data contains four deliberately malformed rows so the data notes have something to show.

## The tags

Thresholds are illustrative starting points, and bank policy sets the final values. `python3 -m engine --list-tags` prints every rule in full, and `docs/tags/` has a card for each tag.

| Group | Tag | Id | What it means |
| --- | --- | --- | --- |
| Income | Salary earner | `salary-earner` | Receives a salary credit every month. |
| Income | Regular non-salary income | `regular-other-income` | Receives regular income other than salary from the same business payer. |
| Income | Irregular income | `irregular-income` | Earns income in most months, but the amount swings a lot from month to month and there is no steady salary. |
| Income | Several income sources | `multi-source-income` | Received earned income from several different payers recently. |
| Income | Business or freelance income | `business-income` | Receives business or freelance income in most months. |
| Income | Remittance receiver | `remittance-receiver` | Regularly receives money sent from abroad. |
| Income | Rising income | `rising-income` | Average monthly earned income in the last 3 months is clearly above the 6 months before. |
| Income | Falling income | `falling-income` | Average monthly earned income in the last 3 months is well below the 6 months before. |
| Income | Large recent inflow | `large-recent-inflow` | Received a single large credit recently, several times the usual monthly money in. |
| Income | High monthly inflow | `high-inflow` | Money coming in averages a high amount per month. |
| Spending pattern | High cash user | `high-cash-user` | Takes out a large part of spending as cash. |
| Spending pattern | Eats out often | `dining-out` | Pays at restaurants and cafés several times a month, most months. |
| Spending pattern | Regular grocery shopper | `groceries-regular` | Buys groceries several times a month, nearly every month. |
| Spending pattern | Regular commuter | `commuter` | Pays for transport or fuel many times a month. |
| Spending pattern | Recent large purchase | `big-ticket-purchase` | Made a single card purchase recently that is large compared with usual card spending. |
| Spending pattern | Spending rising | `spending-rising` | Average monthly spending in the last 3 months is clearly above the 6 months before. |
| Card use | Card-heavy spender | `card-heavy-spender` | Most spending is by card. |
| Card use | Online shopper | `online-shopper` | Makes frequent online card purchases. |
| Card use | Foreign-currency spender | `foreign-currency-spender` | A large part of card spending is in foreign currencies. |
| Card use | Card no longer used | `card-dormant` | Used a card regularly before, but not in the last 3 complete months. |
| Channel and digital use | Digital-first | `digital-first` | Does almost all self-service banking in the app, online banking or with online card payments. |
| Channel and digital use | Branch-reliant | `branch-reliant` | Does much of their self-service banking in a branch. |
| Channel and digital use | Regular cash depositor | `cash-depositor` | Deposits cash in most months. |
| Channel and digital use | Active in the mobile app | `mobile-active` | Uses the mobile app every month and often. |
| Travel | Frequent traveller | `frequent-traveller` | Uses a card or ATM abroad in several different months. |
| Travel | Travelled recently | `recent-traveller` | Used a card or ATM abroad in the last 30 days. |
| Travel | Books travel | `travel-booker` | Pays for flights, hotels or travel agents in several months of the year. |
| Savings and balances | Saver | `saver` | Regularly moves money to savings, or keeps a good part of what comes in. |
| Savings and balances | Investor | `investor` | Buys investments. |
| Savings and balances | Keeps a healthy buffer | `healthy-buffer` | Keeps an average month-end balance of at least three months of spending, and never goes overdrawn. |
| Savings and balances | Balance growing | `balance-growing` | The average month-end balance of the last 3 months is well above the 6 months before. |
| Savings and balances | Large balance, little activity | `idle-balance` | Keeps a large balance but uses the account little; a savings conversation may help. |
| Bills and subscriptions | Regular bill payer | `bill-payer` | Pays utility or phone bills nearly every month. |
| Bills and subscriptions | Rent payer | `rent-payer` | Pays rent nearly every month. |
| Bills and subscriptions | Loan repayer | `loan-repayer` | Makes loan repayments nearly every month. |
| Bills and subscriptions | Insurance payer | `insurance-payer` | Pays insurance premiums regularly (monthly or quarterly). |
| Bills and subscriptions | Subscription user | `subscription-user` | Pays several different subscriptions. |
| Bills and subscriptions | Several recurring bills | `recurring-bills` | Pays at least two bills that recur every month at a steady amount. |
| Bills and subscriptions | Many subscriptions | `many-subscriptions` | Pays four or more subscriptions that recur every month. |
| Transfers | Remittance sender | `remittance-sender` | Regularly sends money abroad. |
| Transfers | Frequent person-to-person transfers | `p2p-transfer-active` | Sends or receives many transfers to and from other people. |
| Engagement and lifecycle | New customer | `new-customer` | Opened their account recently. |
| Engagement and lifecycle | Active | `active-customer` | Uses the account for self-service banking every month. |
| Engagement and lifecycle | Going dormant | `going-dormant` | Self-service activity has dropped sharply compared with before. |
| Engagement and lifecycle | Dormant | `dormant` | No self-service activity for six months. |
| Engagement and lifecycle | Re-engaged | `re-engaged` | Became active again after a long quiet period. |
| Engagement and lifecycle | Established customer | `established-customer` | Has banked here for years and is active nearly every month. |
| Engagement and lifecycle | Salary credits stopped | `salary-moved-away` | Received a salary nearly every month before, none in the last 2 months, but still uses the account. |
| Financial-stress signals | Spending exceeds money in | `spending-exceeds-inflow` | Spent clearly more than came in during most recent months. |
| Financial-stress signals | Frequent bank charges | `frequent-fee-payer` | Pays bank charges often; a better-suited account might avoid them. |
| Financial-stress signals | Repeatedly low balance | `repeated-low-balance` | The balance fell below 100 in several recent months. |
| Financial-stress signals | Overdrawn in several months | `overdrawn-months` | The balance went below zero in at least two recent months. |
| Financial-stress signals | Returned payments | `returned-payments` | Had payments returned unpaid more than once recently. |
| Financial-stress signals | Income gap | `income-gap` | Earned income arrived nearly every month before, but not in the last 2 months. |

## Rule language

Each tag's `rule` is a tree of `all` and `any` nodes over conditions. A condition names a metric, a transaction filter, a time window, an operator and a threshold. The metrics are:

- `count`, `sum`, `max`, `count_per_month`, `sum_per_month`: over the transactions a filter selects in a window;
- `months_where`: how many months in a month window meet a monthly test (count, sum, net flow, net-flow ratio, deviation from the usual month, lowest or closing balance);
- `distinct`: how many distinct counterparties or countries (never which);
- `share` and `ratio`: a part against a whole, or a recent level against an earlier one, with a minimum denominator for thin history;
- `recurring`: how many recurring streams (one payee, regular every `period_months`, in at least `min_occurrences` months, still current, each month's average payment within `amount_tolerance` of the usual amount or within `amount_floor`);
- `days_since_last`, `tenure_days`, `balance` (lowest, latest or average month-end) and `tag`, which lets one tag depend on another.

The loader refuses unknown keys, fields and metrics. It checks that each tag's declared `fields` equal the fields its rule actually reads, that every placeholder in the reason exists, that every window fits in `history_months`, and that the stored `content_hash` matches the content. A rule change therefore needs a new `taxonomy_version`, a new hash and a changelog entry (`python3 -m engine --taxonomy-hash` prints the hash).

The engine computes per-month aggregates (feature buckets) for each customer, feature and calendar month, and answers every window from them; a window edge that cuts a month in two is answered from that month's transactions. The same buckets will be kept in the profile store and updated incrementally (see [DESIGN.md](DESIGN.md)).

## Fairness and privacy rules

These hold everywhere in the plugin. The engine enforces them in code, in `engine/policy.py`, so editing `tags.json` cannot switch them off.

- **Behaviour, never protected traits.** Tags come from what customers do with their accounts. No field, filter, category or tag name may refer to religion, ethnicity, race, caste, national origin, gender, sex, sexual orientation, disability, health, pregnancy, family or marital status, or political opinion.
- **No age by default.** No tag uses age or date of birth, and the engine refuses age fields. Age could only be added by a tag explicitly marked "bank policy decides" plus an engine change.
- **No proxies.** Categories that stand in for protected traits or age are collapsed into `restricted` when read and cannot select transactions: health and medical spending, charity and worship payments, childcare and school fees, and pension income. No rule may select a specific country or currency, so remittance tags use amounts and frequency only, never the corridor, and travel tags say "abroad", never where. Customer names are never read, and the people a customer pays are pseudonymised.
- **Patterns, never causes.** A tag says what was seen ("salary credits stopped"), never why.
- **Explainable, no scores.** Every tag shows its rule and the evidence that produced it. There are no unexplained scores and no combined rating.
- **Intended use and prohibited uses.** Tags are for service and personalisation by a relationship manager. They must never be used for credit decisions, pricing, fraud or AML decisions, or any automated decision with legal or similarly significant effect; financial-stress tags are support signals only. Every tag card says so.
- **Read-only.** The engine never modifies its inputs, and without `--out-dir` it writes nothing at all. The builder writes only the plugin's own profile store; the reader, the skills, the commands and the agent only read.
- **Minimal data.** Only the columns listed in the data contract are loaded.
- **Synthetic data only** in this repository. There is no real customer data, and no bank names, hosts or logins.
- **No model names** appear in code, configuration or docs.

## Skills, commands and the agent

All three are instructions only: they reach data through the reader's read-only tools and never run scripts.

- **Skills.** `customer-tagging` explains a customer's tags in plain words, always with the rule, the evidence and the as-of date, and answers "why not" from the unmet conditions. `segment-explorer` lists the customers holding a tag with care: ids and display names only, one page at a time, one tag per list, and why a customer matched only when asked. `tag-review` takes the taxonomy owner through coverage, prevalence, drift, the fairness report and review dates, and names the changes that need a new assessment.
- **Commands.** `/tag-customers` (a customer's tags, or how many hold each tag), `/explain-customer` (one customer, or why one tag does or does not apply), `/tag-report` (the taxonomy review). Each is under 4,000 bytes and expands no arguments.
- **Agent.** `customer-profiler` has the reader tier, exactly the reader's six tools, the three skills, no model setting, and an output schema it must return.
- **The same four rules in every file:** never change data; never infer or discuss protected traits; refuse requests to tag, sort, rank or select people by a protected trait or a proxy for one; refuse credit, pricing, fraud or AML decisions and any automated decision with legal or similarly significant effect. A test checks each file for them.

## Evaluation, fairness and drift

- **Evaluation scenarios** (`evals/scenarios.json`, format in `evals/README.md`). 54 staff questions: explaining a customer's tags, "why not", segments, tag meanings, review numbers, history, and 13 refusals (protected traits, ranking by a proxy, credit, pricing, AML, collections, and changing or deleting data). Each lists the tool calls expected with exact arguments, the facts the answer must contain and the phrases it must not. `tests/test_evals.py` checks every call against the tool's input schema and every fact against what the reader returns for the synthetic fixture store, so no scenario expects something the tools do not say. Grading an assistant's answers is left to Cognic's runner.
- **Fairness kit** (`tools/fairness.py`). Tests and a report only: neither the engine nor the reader imports it, and the engine is never given the attributes. The kit generates synthetic customers and, in a separate file, synthetic stand-in attributes, tags the customers with the engine, and joins the two itself. Three scenarios: *null* (attributes independent of behaviour: no tag may fail), *planted-proxy* (attributes decide the foreign country of transactions, the restricted category and payee of a monthly payment, and protected columns in the customer file: the engine's output must be identical to the null scenario's) and *canary* (test-only tags reading a behaviour planted to follow an attribute: a strong and a subtle canary must fail, a near miss must not). Per tag and attribute it reports group rates, the four-fifths impact ratio with its interval, Bonferroni-corrected tests (Fisher's exact test for small cells), Cramer's V and the uncertainty coefficient, and the chance level from shuffled attributes. `tests/test_fairness.py` runs it small; `.github/workflows/fairness.yml` runs it at 383,600 customers, enough for every tag to reach 350 tagged customers in the smallest group, and fails on the gate. The report is `docs/fairness-report.md`.
- **Drift** (`tools/drift.py`). The builder records, with every rebuild and every tick that moves the as-of date, how many customers hold, are suppressed for or cannot be evaluated for each tag, and how many tags each customer holds (migration 0003; counts only). The drift report compares each run with a frozen baseline (the first three runs after a taxonomy change): WARN at a 25% relative change of at least 1 point, ALERT at 50% and 2 points, both needing p below 0.01; a tag falling to zero, a 20% population change and the spread's stability index also alert. It reads several stores, since a rebuilt store keeps only its latest run. `docs/drift-report.md` is an example from the synthetic data followed month by month.

## Governance

`docs/governance/` holds generic, jurisdiction-neutral templates, each marked "to be completed by the bank's compliance team": a DPIA-style assessment (screening against the high-risk criteria, purpose, profiling mode and risk class, data, necessity, risks and mitigations, sign-off), customer rights (explanation, objection and the opt-out the builder honours, access and correction), retention, the audit trail (the `runs` table and the store export) and taxonomy change control (version bump, content hash, changelog, reviewer, tag cards, fairness run). They describe what the plugin does and leave every decision that belongs to the bank blank; a test keeps them free of any named law or regulator.

## Cognic safety file

`cognic.plugin.json` is a draft written against Cognic's draft safety-file schema (`schemaVersion` "1-draft"). It declares:

- the read effect only, with consent class "none", data classes "confidential" and "sensitive", and the `employee` role;
- three skills and three commands at the "instruction" tier with the "standard" profile, requiring only the reader's tools;
- one agent, `customer-profiler`, at the "reader" tier with the reader's six tools, the three skills and its output schema;
- one server, `profiles`: stdio, `/app/profile-reader --store /data/profile.db`, network denied, no credentials, the image pinned by its reproducible digest, and the `toolListDigest` of its tool list;
- six tools, each with effect "read", tier "reader", enforcement "read-only", and strict input and output schemas;
- no hooks and no dependencies. The builder, which writes the profile store (a "private" effect), is not declared until hosting says how such a process is admitted (`docs/OPEN-QUESTIONS.md`, Q11).

Points to settle when plugin hosting lands are kept in `docs/OPEN-QUESTIONS.md`: the personal data class (Q2), skill and tool reference forms (Q4, Q33), the roles (Q5), and where the image is published (Q31).

**Validation.** No JSON-schema package is installed, so `tools/validate_safety_file.py` is a small standard-library validator. It implements every keyword the draft schema uses and fails on any keyword it does not know. It is not a general JSON Schema implementation. The draft schema is not in this public repository. The safety-file schema test runs only when `COGNIC_SAFETY_SCHEMA` points to it; otherwise it is skipped.

```bash
COGNIC_SAFETY_SCHEMA=/path/to/draft-schema.json python3 -m unittest tests.test_safety_file
```

## Licence

All rights reserved; see `LICENSE`. This repository is public for visibility and CI only; no licence to use the code is granted.

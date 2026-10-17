# Cognic customer tagging

A plugin for Cognic that tags customers from their transactions and profile. Every tag is explained by the rule and the evidence that produced it.

**Status:** stage 1 is complete, as content and logic only:
- the tag taxonomy and rules as data (`taxonomy/tags.json`, 33 tags);
- a deterministic rules engine (`engine/`);
- seeded synthetic data with expected tags for a labelled subset (`data/`), and tests (`tests/`);
- a skill and a command that explain tags read-only, and a draft Cognic safety file.

Later stages add scheduled runs and then real-time profiles, once Cognic's plugin hosting is available. See [DESIGN.md](DESIGN.md).

## What it does

The engine reads `customers.csv` and `transactions.csv` and applies the rules in `taxonomy/tags.json`. For each customer it returns the tags whose rules were met. Each tag comes with:

- a **reason** in plain words, for example "salary credited monthly, 6 of last 6 months, about 3,000.00 USD a month";
- the **rule**, for example "months with a salary credit, in the last 6 complete months: at least 6";
- the **evidence**: every number the rule looked at, its threshold, the dates it covered and the months that counted.

A tag whose rule needs a missing field, such as an account opening date, is reported as "not evaluated" with the missing field. It is never guessed.

## Layout

| Path | What it is |
| --- | --- |
| `.claude-plugin/plugin.json` | Claude Code plugin manifest |
| `skills/customer-tagging/SKILL.md` | How the agent runs the engine and explains tags, read-only |
| `commands/tag-customers.md` | Command that loads the skill |
| `cognic.plugin.json` | Draft Cognic safety file |
| `taxonomy/tags.json` | The tags: fields, rules, thresholds, windows and reasons |
| `engine/` | The rules engine, Python standard library only |
| `data/generate.py` | Seeded synthetic data generator |
| `data/*.csv`, `data/expected_tags.json` | Generated data and the labelled subset's expected tags |
| `tests/` | `unittest` suite; latest results in `tests/RESULTS.md` |
| `tools/validate_safety_file.py` | Standard-library validator for the safety file |
| `.github/workflows/tests.yml` | CI: runs the tests on Python 3.9 to 3.13 |
| `docs/STATUS.md`, `docs/OPEN-QUESTIONS.md` | Build status per phase, and the questions only Cognic's hosting can settle |
| `DESIGN.md` | Stages 2 and 3, and the compliance review |

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

Other options: `--as-of YYYY-MM-DD` tags as of a past date; the default is the latest transaction date in the file, never today's date. `--include-unmet` also lists the tags that did not apply, with their evidence.

Regenerate the synthetic data, which gives byte-identical files for the same seed:

```bash
python3 data/generate.py
```

Run the tests:

```bash
python3 -m unittest discover -s tests -t .
```

CI runs the same command on Python 3.9 to 3.13 on every push and pull request (`.github/workflows/tests.yml`). The draft safety-file schema is private and stays out of this repository and its CI, so CI skips that one test; run it locally with `COGNIC_SAFETY_SCHEMA` set (see `docs/OPEN-QUESTIONS.md`, Q1).

## Data contract

`customers.csv` needs `customer_id`. The engine also reads `account_open_date` for tenure rules, `home_country` for "abroad" rules and `home_currency`, which defaults to the base currency. It reads no other column. Names, account numbers and any protected-trait column are ignored and never loaded.

`transactions.csv` needs `customer_id`, `posted_date` and `amount`. It may also have `txn_id`, `currency`, `direction`, `channel`, `category`, `counterparty` and `txn_country`.

- **Signs.** With a `direction` of credit or debit, the amount may be unsigned, or signed with money out negative. Without a direction, a negative amount is a debit and a positive amount a credit. A negative credit is a contradiction and is skipped.
- **Currency.** Amounts are converted to the base currency with the fixed rate table in `tags.json`. An empty currency means the customer's home currency. An unknown currency is skipped, never guessed.
- **Bad rows.** Rows with a bad date, amount or direction, a zero amount, an unknown customer or a duplicate `txn_id` are skipped. Every skip is counted by reason in the output's data notes.
- **Time windows.** Day windows end on the as-of date. Month windows use complete calendar months, so a mid-month as-of date does not count the partial month.

The generated data contains four deliberately malformed rows so the data notes have something to show.

## The tags

Thresholds are illustrative starting points, and bank policy sets the final values. `python3 -m engine --list-tags` prints every rule in full.

| Group | Tag | Id | What it means |
| --- | --- | --- | --- |
| income | Salary earner | `salary-earner` | Receives a salary credit every month. |
| income | Irregular income | `irregular-income` | Earns income in most months, but the amount swings a lot from month to month and there is no steady salary. |
| income | Several income sources | `multi-source-income` | Received earned income from several different payers recently. |
| income | Business or freelance income | `business-income` | Receives business or freelance income in most months. |
| income | Remittance receiver | `remittance-receiver` | Regularly receives money sent from abroad. |
| income | Rising income | `rising-income` | Average monthly earned income in the last 3 months is clearly above the 6 months before. |
| income | Falling income | `falling-income` | Average monthly earned income in the last 3 months is well below the 6 months before. |
| income | Large recent inflow | `large-recent-inflow` | Received a single large credit recently, several times the usual monthly money in. |
| income | High monthly inflow | `high-inflow` | Money coming in averages a high amount per month. |
| payments | Regular bill payer | `bill-payer` | Pays utility or phone bills nearly every month. |
| payments | Rent payer | `rent-payer` | Pays rent nearly every month. |
| payments | Loan repayer | `loan-repayer` | Makes loan repayments nearly every month. |
| payments | Insurance payer | `insurance-payer` | Pays insurance premiums regularly (monthly or quarterly). |
| payments | Remittance sender | `remittance-sender` | Regularly sends money abroad. |
| payments | Frequent person-to-person transfers | `p2p-transfer-active` | Sends or receives many transfers to and from other people. |
| payments | Subscription user | `subscription-user` | Pays several different subscriptions. |
| payments | Frequent bank charges | `frequent-fee-payer` | Pays bank charges often; a better-suited account might avoid them. |
| spending | Card-heavy spender | `card-heavy-spender` | Most spending is by card. |
| spending | Online shopper | `online-shopper` | Makes frequent online card purchases. |
| spending | High cash user | `high-cash-user` | Takes out a large part of spending as cash. |
| spending | Foreign-currency spender | `foreign-currency-spender` | A large part of card spending is in foreign currencies. |
| channels | Digital-first | `digital-first` | Does almost all self-service banking in the app, online banking or with online card payments. |
| channels | Branch-reliant | `branch-reliant` | Does much of their self-service banking in a branch. |
| channels | Regular cash depositor | `cash-depositor` | Deposits cash in most months. |
| saving | Saver | `saver` | Regularly moves money to savings, or keeps a good part of what comes in. |
| saving | Investor | `investor` | Buys investments. |
| saving | Spending exceeds money in | `spending-exceeds-inflow` | Spent clearly more than came in during most recent months. |
| travel | Frequent traveller | `frequent-traveller` | Uses a card or ATM abroad in several different months. |
| engagement | New customer | `new-customer` | Opened their account recently. |
| engagement | Established customer | `established-customer` | Has banked here for years and is active nearly every month. |
| engagement | Going dormant | `going-dormant` | Self-service activity has dropped sharply compared with before. |
| engagement | Dormant | `dormant` | No self-service activity for six months. |
| engagement | Re-engaged | `re-engaged` | Became active again after a long quiet period. |

## Rule language

Each tag's `rule` is a tree of `all` and `any` nodes over conditions. A condition names a metric, a transaction filter, a time window, an operator and a threshold. The metrics are `count`, `sum`, `max`, `count_per_month`, `sum_per_month`, `months_where`, `distinct`, `share`, `ratio`, `tenure_days` and `tag`; the last lets one tag depend on another. The loader refuses unknown keys, fields and metrics. It also checks that each tag's declared `fields` equal the fields its rule actually reads, and that every placeholder in the reason exists. The engine's docstrings describe each metric.

## Fairness and privacy rules

These hold everywhere in the plugin. The engine enforces them in code, in `engine/policy.py`, so editing `tags.json` cannot switch them off.

- **Behaviour, never protected traits.** Tags come from what customers do with their accounts. No field, filter or category may refer to religion, ethnicity, race, caste, gender, sex, disability, marital status or pregnancy.
- **No age by default.** No tag uses age or date of birth, and the engine refuses age fields. Age could only be added by a tag explicitly marked "bank policy decides" plus an engine change.
- **No proxies.** Categories that stand in for protected traits or age cannot select transactions: health and medical spending, charity and worship payments, childcare and school fees, and pension income. Customer names are never read.
- **Explainable, no scores.** Every tag shows its rule and the evidence that produced it. There are no unexplained scores and no combined rating.
- **Read-only.** The engine never modifies its inputs. Without `--out-dir` it writes nothing at all, and the skill always runs it that way.
- **Minimal data.** Only the columns listed in the data contract are loaded.
- **Synthetic data only** in this repository. There is no real customer data, and no bank names, hosts or logins.
- **No model names** appear in code or configuration.

## Cognic safety file

`cognic.plugin.json` is a draft written against Cognic's draft safety-file schema (`schemaVersion` "1-draft"). It declares:

- the read effect only, with consent class "none";
- data classes "confidential" and "sensitive";
- one skill and one command, both at the "instruction" tier with the "workbench" profile, because the skill runs the engine's scripts;
- no hooks, servers, tools, agents or dependencies.

Points to settle when plugin hosting lands:

- **Personal data class.** The draft vocabulary has no "personal" data class, so "sensitive" stands for personal data here.
- **Workbench effect.** If the harness counts any workbench script run as a private effect, `effects` becomes ["read", "private"] and the skill moves to the "worker" tier. Nothing else changes.
- **Roles.** Every `scope.roles` is `["employee"]`, a broad role. A bank narrows access later through its own role bindings, and the name must match an actual admin role binding.

**Validation.** No JSON-schema package is installed, so `tools/validate_safety_file.py` is a small standard-library validator. It implements every keyword the draft schema uses and fails on any keyword it does not know. It is not a general JSON Schema implementation. The draft schema is not in this public repository. The safety-file schema test runs only when `COGNIC_SAFETY_SCHEMA` points to it; otherwise it is skipped.

```bash
COGNIC_SAFETY_SCHEMA=/path/to/draft-schema.json python3 -m unittest tests.test_safety_file
```

## Licence

All rights reserved; see `LICENSE`. This repository is public for visibility and CI only; no licence to use the code is granted.

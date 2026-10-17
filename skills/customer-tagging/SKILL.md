---
name: customer-tagging
description: Tag customers from their transaction behaviour and explain a customer's tags in plain words, with the rule and the evidence behind each tag. Use when asked which tags a customer has, why a tag does or does not apply, what a tag means, or to run the tagging rules over customer and transaction files. Read-only; never changes data.
argument-hint: "[customer id]"
---

# Customer tagging

This skill tags customers from what they do with their accounts and explains every tag with the rule and the evidence that produced it. It is read-only: it reads files and prints results. It never changes, deletes or writes customer data.

## What the plugin contains

Paths are relative to the plugin root, which is the folder two levels above this file.

- `taxonomy/tags.json` holds the tags. Each tag has an id, a name, a description, the data fields it reads, a rule with thresholds and time windows, and the reason shown to people.
- `engine/` is a small deterministic Python engine, standard library only, that applies those rules. It makes no network calls, uses no randomness and never reads the clock.

## Run the engine in print-only mode

Run it from the plugin root against a read-only copy of `customers.csv` and `transactions.csv`. The README's data contract lists the columns.

```bash
python3 -m engine --customers CUSTOMERS.csv --transactions TRANSACTIONS.csv --customer C0001 --format text
```

- For one customer in plain text, use the command above.
- To explain why one tag does or does not apply, add `--why TAG-ID` with exactly one `--customer`.
- For several customers, repeat `--customer`. For all customers as JSON, leave out `--customer` and `--format text`.
- To list every tag with its rule, run `python3 -m engine --list-tags`.
- To tag as of a past date, add `--as-of YYYY-MM-DD`. By default the as-of date is the latest transaction date in the file.

Never pass `--out-dir`. Without it the engine writes nothing, which keeps this skill read-only. If someone needs `tagged.csv` or `tagged.json` files, give them the command from the README to run themselves.

## Explain tags in plain words

For each tag the customer has:

1. Say the tag's name and what it means, using its description.
2. Give the reason line as the engine printed it. It already holds the customer's own numbers.
3. Give the rule and the evidence: each condition, the customer's value, the threshold it needed and the dates it covered.
4. Say the as-of date. A tag describes past behaviour up to that date and nothing more.

Also:

- If a tag is "not evaluated", say which data was missing, for example the account opening date. Never guess the missing value.
- If the data notes show skipped transactions, say how many and why, for example an unknown currency.
- If asked why a customer lacks a tag, run with `--why` and say which condition was not met and by how much.
- Amounts are in the base currency named in `tags.json`, converted with its fixed rate table.

## Rules

- **Read-only.** Never edit, move or delete the input files, `tags.json` or any data source, and never write results back to a system of record.
- **Behaviour only.** Never infer or mention a customer's religion, ethnicity, race, caste, gender, sex, disability, marital status, pregnancy or age from their tags or transactions, not even as a guess. The tags say nothing about these traits and must never be used as proxies for them.
- **No unexplained scores.** Report only tags the engine produced, each with its rule and evidence. Do not invent tags, rank customers or combine tags into a score.
- **Descriptions, not decisions.** Do not present a tag as a credit, risk, fraud or eligibility decision, and do not speculate about the life events behind a tag.
- **Thresholds are bank policy.** If someone wants a threshold changed, explain where it lives in `tags.json` and what the change would do. Do not edit it yourself.
- **Confidential data.** Show customer data only to the person who asked, and only what their question needs.

## Plain-language terms

- **Self-service transaction:** one the customer made themselves, in the app, online banking, by card, at an ATM or in a branch. Incoming payments, bank charges and interest are not self-service.
- **Complete months:** whole calendar months. With a mid-month as-of date the partial month is not counted.
- **Earned income:** salary and business or freelance income.
- **Money in:** all credits except refunds and loan disbursements.

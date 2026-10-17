# Frequent bank charges (`frequent-fee-payer`)

- **Group:** Financial-stress signals
- **Polarity:** burden (a support signal; a customer could be disadvantaged if it were misused)
- **Taxonomy version:** 2.0.0
- **Support only:** offer help; never use for credit, pricing, collections or sales targeting.

## Purpose

Pays bank charges often; a better-suited account might avoid them.

## Rule in words

bank charges, in the last 90 days: at least 3

## Conditions

| Condition | Window | Needs |
| --- | --- | --- |
| bank charges | the last 90 days | at least 3 |

Also shown as evidence, never part of the decision:

- bank charges paid (the last 90 days)

The reason shown to staff: "{fee_count} bank charges in the last 90 days, {fee_total} in total", with every placeholder filled from the evidence.

## Data used

- `transactions.amount`
- `transactions.category`
- `transactions.currency`
- `transactions.direction`
- `transactions.posted_date`

No other column is read. Names, account numbers and protected-trait columns are never loaded.

## Lifecycle

Evaluated at the as-of date. History is recorded at month-end checkpoints: `entered_on` is the first month end of the current run at which the tag held; a tag that started after the last month end is "new this month".

## Intended use

Service and personalisation by a relationship manager: understanding a customer's behaviour to offer relevant help and products. Tags inform a person; they never act on their own.

## Prohibited uses

- credit decisions of any kind, including limits and affordability
- pricing, fees or interest rates
- fraud, AML or other financial-crime decisions
- any automated decision with legal or similarly significant effect on the customer
- collections, or targeting sales at customers flagged by financial-stress signals

## Known limitations

- Counts charges, not their cause.
- A support signal only: never for credit, pricing or collections.

## Owner and review

- **Owner:** The bank's taxonomy owner (to be named by the bank)
- **Review date:** 2027-04-30

---

Generated from `taxonomy/tags.json` by `python3 -m engine.cards`; do not edit by hand.

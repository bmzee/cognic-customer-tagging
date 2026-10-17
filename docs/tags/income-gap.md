# Income gap (`income-gap`)

- **Group:** Financial-stress signals
- **Polarity:** burden (a support signal; a customer could be disadvantaged if it were misused)
- **Taxonomy version:** 2.0.0
- **Support only:** offer help; never use for credit, pricing, collections or sales targeting.

## Purpose

Earned income arrived nearly every month before, but not in the last 2 months.

## Rule in words

months with earned income (salary or business income) [each month: count >= 1], in the 6 complete months before the last 2: at least 5 AND earned income credits, in the last 2 complete months: at most 0

## Conditions

| Condition | Window | Needs |
| --- | --- | --- |
| months with earned income (salary or business income) | the 6 complete months before the last 2 | at least 5 |
| earned income credits | the last 2 complete months | at most 0 |

The reason shown to staff: "earned income in {earned_before} of the 6 months before, none in the last 2 complete months", with every placeholder filled from the evidence.

## Data used

- `transactions.category`
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

- States only the pattern seen; it never says why income stopped.
- A support signal only: never for credit, pricing or collections.

## Owner and review

- **Owner:** The bank's taxonomy owner (to be named by the bank)
- **Review date:** 2027-04-30

---

Generated from `taxonomy/tags.json` by `python3 -m engine.cards`; do not edit by hand.

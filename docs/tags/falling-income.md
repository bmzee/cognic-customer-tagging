# Falling income (`falling-income`)

- **Group:** Income
- **Polarity:** burden (a support signal; a customer could be disadvantaged if it were misused)
- **Taxonomy version:** 2.0.0

## Purpose

Average monthly earned income in the last 3 months is well below the 6 months before.

## Rule in words

average monthly earned income, recent against earlier (the last 3 complete months vs the 6 complete months before the last 3): at most 60%

## Conditions

| Condition | Window | Needs |
| --- | --- | --- |
| average monthly earned income, recent against earlier | the last 3 complete months vs the 6 complete months before the last 3 | at most 60% |

The reason shown to staff: "average monthly earned income fell to {income_change} of its earlier level: {income_change.numerator} a month in the last 3 months against {income_change.denominator} in the 6 months before", with every placeholder filled from the evidence.

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

- Does not say why income fell and must never be read as a cause.

## Owner and review

- **Owner:** The bank's taxonomy owner (to be named by the bank)
- **Review date:** 2027-04-30

---

Generated from `taxonomy/tags.json` by `python3 -m engine.cards`; do not edit by hand.

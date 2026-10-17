# Large recent inflow (`large-recent-inflow`)

- **Group:** Income
- **Polarity:** neutral (describes behaviour without implying an offer or a burden)
- **Taxonomy version:** 2.0.0

## Purpose

Received a single large credit recently, several times the usual monthly money in.

## Rule in words

largest single credit, in the last 3 complete months: at least 5,000.00 USD AND largest single credit against the usual monthly money in (the last 3 complete months vs the 6 complete months before the last 3): at least 3 times

## Conditions

| Condition | Window | Needs |
| --- | --- | --- |
| largest single credit | the last 3 complete months | at least 5,000.00 USD |
| largest single credit against the usual monthly money in | the last 3 complete months vs the 6 complete months before the last 3 | at least 3 times |

The reason shown to staff: "a single credit of {largest} in the last 3 months, {inflow_ratio} the usual monthly money in of {inflow_ratio.denominator} in the 6 months before", with every placeholder filled from the evidence.

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

- A large credit may be a transfer between the customer's own accounts at another bank.

## Owner and review

- **Owner:** The bank's taxonomy owner (to be named by the bank)
- **Review date:** 2027-04-30

---

Generated from `taxonomy/tags.json` by `python3 -m engine.cards`; do not edit by hand.

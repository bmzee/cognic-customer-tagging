# Active (`active-customer`)

- **Group:** Engagement and lifecycle
- **Polarity:** benefit (a customer may be offered something because of it)
- **Taxonomy version:** 2.0.0

## Purpose

Uses the account for self-service banking every month.

## Rule in words

months with self-service activity [each month: count >= 1], in the last 3 complete months: at least 3

## Conditions

| Condition | Window | Needs |
| --- | --- | --- |
| months with self-service activity | the last 3 complete months | at least 3 |

The reason shown to staff: "self-service activity in {active_months} of the last 3 complete months", with every placeholder filled from the evidence.

## Data used

- `transactions.channel`
- `transactions.posted_date`

No other column is read. Names, account numbers and protected-trait columns are never loaded.

## Lifecycle

Part of the exclusive `lifecycle` group: One lifecycle stage per customer, checked in this order; the first that holds wins and the others are reported as suppressed.. Priority: `dormant`, `going-dormant`, `re-engaged`, `new-customer`, `active-customer`.

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

- Interest, fees and incoming payments do not count as activity.

## Owner and review

- **Owner:** The bank's taxonomy owner (to be named by the bank)
- **Review date:** 2027-04-30

---

Generated from `taxonomy/tags.json` by `python3 -m engine.cards`; do not edit by hand.

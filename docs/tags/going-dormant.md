# Going dormant (`going-dormant`)

- **Group:** Engagement and lifecycle
- **Polarity:** neutral (describes behaviour without implying an offer or a burden)
- **Taxonomy version:** 2.0.0

## Purpose

Self-service activity has dropped sharply compared with before.

## Rule in words

self-service transactions per month, recent against earlier (the last 90 days vs the 270 days before the last 90 days): at most 25% AND Dormant tag applies: no

## Conditions

| Condition | Window | Needs |
| --- | --- | --- |
| self-service transactions per month, recent against earlier | the last 90 days vs the 270 days before the last 90 days | at most 25% |
| Dormant tag applies | at the as-of date | no |

The reason shown to staff: "self-service activity fell to {activity_change} of its earlier level: on average {activity_change.numerator} a month in the last 90 days against {activity_change.denominator} a month in the 270 days before", with every placeholder filled from the evidence.

## Data used

- `customers.account_open_date`
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

- Activity moved to another account of the same customer looks like a drop.

## Owner and review

- **Owner:** The bank's taxonomy owner (to be named by the bank)
- **Review date:** 2027-04-30

---

Generated from `taxonomy/tags.json` by `python3 -m engine.cards`; do not edit by hand.

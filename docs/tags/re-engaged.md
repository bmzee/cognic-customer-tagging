# Re-engaged (`re-engaged`)

- **Group:** Engagement and lifecycle
- **Polarity:** neutral (describes behaviour without implying an offer or a burden)
- **Taxonomy version:** 2.0.0

## Purpose

Became active again after a long quiet period.

## Rule in words

self-service transactions, in the last 90 days: at least 6 AND self-service transactions, in the 180 days before the last 90 days: at most 1 AND days since the account was opened: at least 270 days

## Conditions

| Condition | Window | Needs |
| --- | --- | --- |
| self-service transactions | the last 90 days | at least 6 |
| self-service transactions | the 180 days before the last 90 days | at most 1 |
| days since the account was opened | since the account opened | at least 270 days |

The reason shown to staff: "{recent_count} self-service transactions in the last 90 days after {earlier_count} in the 180 days before", with every placeholder filled from the evidence.

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

- A single burst of activity can trigger it; the next month-end check shows whether it lasts.

## Owner and review

- **Owner:** The bank's taxonomy owner (to be named by the bank)
- **Review date:** 2027-04-30

---

Generated from `taxonomy/tags.json` by `python3 -m engine.cards`; do not edit by hand.

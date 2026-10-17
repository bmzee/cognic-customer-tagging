# Active in the mobile app (`mobile-active`)

- **Group:** Channel and digital use
- **Polarity:** neutral (describes behaviour without implying an offer or a burden)
- **Taxonomy version:** 2.0.0

## Purpose

Uses the mobile app every month and often.

## Rule in words

months with a mobile app transaction [each month: count >= 1], in the last 3 complete months: at least 3 AND mobile app transactions, in the last 90 days: at least 6

## Conditions

| Condition | Window | Needs |
| --- | --- | --- |
| months with a mobile app transaction | the last 3 complete months | at least 3 |
| mobile app transactions | the last 90 days | at least 6 |

The reason shown to staff: "uses the mobile app every month: {app_txns} app transactions in the last 90 days", with every placeholder filled from the evidence.

## Data used

- `transactions.channel`
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

- Counts transactions made in the app, not logins or balance checks.

## Owner and review

- **Owner:** The bank's taxonomy owner (to be named by the bank)
- **Review date:** 2027-04-30

---

Generated from `taxonomy/tags.json` by `python3 -m engine.cards`; do not edit by hand.

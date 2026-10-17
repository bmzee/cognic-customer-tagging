# Digital-first (`digital-first`)

- **Group:** Channel and digital use
- **Polarity:** neutral (describes behaviour without implying an offer or a burden)
- **Taxonomy version:** 2.0.0

## Purpose

Does almost all self-service banking in the app, online banking or with online card payments.

## Rule in words

share of self-service transactions made digitally, in the last 90 days: at least 80% AND self-service transactions, in the last 90 days: at least 10

## Conditions

| Condition | Window | Needs |
| --- | --- | --- |
| share of self-service transactions made digitally | the last 90 days | at least 80% |
| self-service transactions | the last 90 days | at least 10 |

The reason shown to staff: "{digital_share} of {self_count} self-service transactions in the last 90 days were in the app, online banking or online card payments", with every placeholder filled from the evidence.

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

- Counts transactions, not logins: someone who checks the app but pays in a branch is not digital-first.

## Owner and review

- **Owner:** The bank's taxonomy owner (to be named by the bank)
- **Review date:** 2027-04-30

---

Generated from `taxonomy/tags.json` by `python3 -m engine.cards`; do not edit by hand.

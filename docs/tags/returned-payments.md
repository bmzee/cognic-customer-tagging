# Returned payments (`returned-payments`)

- **Group:** Financial-stress signals
- **Polarity:** burden (a support signal; a customer could be disadvantaged if it were misused)
- **Taxonomy version:** 2.0.0
- **Support only:** offer help; never use for credit, pricing, collections or sales targeting.

## Purpose

Had payments returned unpaid more than once recently.

## Rule in words

payments returned unpaid, in the last 180 days: at least 2

## Conditions

| Condition | Window | Needs |
| --- | --- | --- |
| payments returned unpaid | the last 180 days | at least 2 |

The reason shown to staff: "{returned} payments returned unpaid in the last 180 days", with every placeholder filled from the evidence.

## Data used

- `transactions.category`
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

- A support signal only: never for credit, pricing or collections.
- Depends on the bank labelling returned payments.

## Owner and review

- **Owner:** The bank's taxonomy owner (to be named by the bank)
- **Review date:** 2027-04-30

---

Generated from `taxonomy/tags.json` by `python3 -m engine.cards`; do not edit by hand.

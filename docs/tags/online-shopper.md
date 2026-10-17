# Online shopper (`online-shopper`)

- **Group:** Card use
- **Polarity:** neutral (describes behaviour without implying an offer or a burden)
- **Taxonomy version:** 2.0.0

## Purpose

Makes frequent online card purchases.

## Rule in words

online card purchases, in the last 90 days: at least 8

## Conditions

| Condition | Window | Needs |
| --- | --- | --- |
| online card purchases | the last 90 days | at least 8 |

The reason shown to staff: "{online_count} online card purchases in the last 90 days", with every placeholder filled from the evidence.

## Data used

- `transactions.channel`
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

- Relies on the online channel flag from the card network.

## Owner and review

- **Owner:** The bank's taxonomy owner (to be named by the bank)
- **Review date:** 2027-04-30

---

Generated from `taxonomy/tags.json` by `python3 -m engine.cards`; do not edit by hand.

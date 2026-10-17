# Regular commuter (`commuter`)

- **Group:** Spending pattern
- **Polarity:** neutral (describes behaviour without implying an offer or a burden)
- **Taxonomy version:** 2.0.0

## Purpose

Pays for transport or fuel many times a month.

## Rule in words

months with at least 6 transport or fuel payments [each month: count >= 6], in the last 6 complete months: at least 4

## Conditions

| Condition | Window | Needs |
| --- | --- | --- |
| months with at least 6 transport or fuel payments | the last 6 complete months | at least 4 |

The reason shown to staff: "regular transport or fuel spending: 6 or more payments in {commute_months} of the last 6 complete months", with every placeholder filled from the evidence.

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

- A monthly travel pass bought once a month does not count as commuting.

## Owner and review

- **Owner:** The bank's taxonomy owner (to be named by the bank)
- **Review date:** 2027-04-30

---

Generated from `taxonomy/tags.json` by `python3 -m engine.cards`; do not edit by hand.

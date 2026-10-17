# Saver (`saver`)

- **Group:** Savings and balances
- **Polarity:** benefit (a customer may be offered something because of it)
- **Taxonomy version:** 2.0.0

## Purpose

Regularly moves money to savings, or keeps a good part of what comes in.

## Rule in words

months with a transfer to savings [each month: count >= 1], in the last 6 complete months: at least 5 OR months where at least 20% of money in was kept (interest not counted) [each month: net flow ratio >= 0.2], in the last 12 complete months: at least 9

## Conditions

| Condition | Window | Needs |
| --- | --- | --- |
| months with a transfer to savings | the last 6 complete months | at least 5 |
| months where at least 20% of money in was kept (interest not counted) | the last 12 complete months | at least 9 |

The reason shown to staff: "moved money to savings in {transfer_months} of last 6 months; kept 20% or more of money in during {surplus_months} of last 12 months", with every placeholder filled from the evidence.

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

- Savings held at another bank are not seen.

## Owner and review

- **Owner:** The bank's taxonomy owner (to be named by the bank)
- **Review date:** 2027-04-30

---

Generated from `taxonomy/tags.json` by `python3 -m engine.cards`; do not edit by hand.

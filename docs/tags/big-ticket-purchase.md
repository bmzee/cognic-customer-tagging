# Recent large purchase (`big-ticket-purchase`)

- **Group:** Spending pattern
- **Polarity:** neutral (describes behaviour without implying an offer or a burden)
- **Taxonomy version:** 2.0.0

## Purpose

Made a single card purchase recently that is large compared with usual card spending.

## Rule in words

largest single card purchase, in the last 3 complete months: at least 1,500.00 USD AND largest card purchase against usual monthly card spending (the last 3 complete months vs the 6 complete months before the last 3): at least 1.5 times

## Conditions

| Condition | Window | Needs |
| --- | --- | --- |
| largest single card purchase | the last 3 complete months | at least 1,500.00 USD |
| largest card purchase against usual monthly card spending | the last 3 complete months vs the 6 complete months before the last 3 | at least 1.5 times |

The reason shown to staff: "a recent large purchase of {largest_purchase}, {purchase_vs_usual} the usual monthly card spending of {purchase_vs_usual.denominator}", with every placeholder filled from the evidence.

## Data used

- `transactions.amount`
- `transactions.channel`
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

- A purchase paid by transfer or in instalments is not seen as one large purchase.

## Owner and review

- **Owner:** The bank's taxonomy owner (to be named by the bank)
- **Review date:** 2027-04-30

---

Generated from `taxonomy/tags.json` by `python3 -m engine.cards`; do not edit by hand.

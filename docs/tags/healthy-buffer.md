# Keeps a healthy buffer (`healthy-buffer`)

- **Group:** Savings and balances
- **Polarity:** benefit (a customer may be offered something because of it)
- **Taxonomy version:** 2.0.0

## Purpose

Keeps an average month-end balance of at least three months of spending, and never goes overdrawn.

## Rule in words

average month-end balance against average monthly spending (the last 6 complete months vs the last 6 complete months): at least 3 times AND lowest balance, in the last 6 complete months: at least 0.00 USD

## Conditions

| Condition | Window | Needs |
| --- | --- | --- |
| average month-end balance against average monthly spending | the last 6 complete months vs the last 6 complete months | at least 3 times |
| lowest balance | the last 6 complete months | at least 0.00 USD |

The reason shown to staff: "keeps a buffer of {buffer_months} monthly spending ({buffer_months.numerator} against {buffer_months.denominator} a month), lowest balance {lowest_balance}", with every placeholder filled from the evidence.

## Data used

- `transactions.amount`
- `transactions.balance_after`
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

- Needs the balance after each transaction; without it the tag is not evaluated.
- Money kept in other accounts is not seen.

## Owner and review

- **Owner:** The bank's taxonomy owner (to be named by the bank)
- **Review date:** 2027-04-30

---

Generated from `taxonomy/tags.json` by `python3 -m engine.cards`; do not edit by hand.

# Balance growing (`balance-growing`)

- **Group:** Savings and balances
- **Polarity:** benefit (a customer may be offered something because of it)
- **Taxonomy version:** 2.0.0

## Purpose

The average month-end balance of the last 3 months is well above the 6 months before.

## Rule in words

average month-end balance, recent against earlier (the last 3 complete months vs the 6 complete months before the last 3): at least 150%

## Conditions

| Condition | Window | Needs |
| --- | --- | --- |
| average month-end balance, recent against earlier | the last 3 complete months vs the 6 complete months before the last 3 | at least 150% |

The reason shown to staff: "month-end balance grew to {balance_change} of its earlier level: {balance_change.numerator} against {balance_change.denominator}", with every placeholder filled from the evidence.

## Data used

- `transactions.balance_after`
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
- A single large credit can lift the balance without any change in habits.

## Owner and review

- **Owner:** The bank's taxonomy owner (to be named by the bank)
- **Review date:** 2027-04-30

---

Generated from `taxonomy/tags.json` by `python3 -m engine.cards`; do not edit by hand.

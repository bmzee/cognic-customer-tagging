# Business or freelance income (`business-income`)

- **Group:** Income
- **Polarity:** neutral (describes behaviour without implying an offer or a burden)
- **Taxonomy version:** 2.0.0

## Purpose

Receives business or freelance income in most months.

## Rule in words

months with business or freelance income [each month: count >= 1], in the last 6 complete months: at least 4

## Conditions

| Condition | Window | Needs |
| --- | --- | --- |
| months with business or freelance income | the last 6 complete months | at least 4 |

The reason shown to staff: "business or freelance income received in {business_months} of last 6 months", with every placeholder filled from the evidence.

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

- Depends on the bank's business-income category; informal income paid as transfers is missed.

## Owner and review

- **Owner:** The bank's taxonomy owner (to be named by the bank)
- **Review date:** 2027-04-30

---

Generated from `taxonomy/tags.json` by `python3 -m engine.cards`; do not edit by hand.

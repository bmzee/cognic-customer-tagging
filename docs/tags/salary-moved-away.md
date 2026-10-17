# Salary credits stopped (`salary-moved-away`)

- **Group:** Engagement and lifecycle
- **Polarity:** neutral (describes behaviour without implying an offer or a burden)
- **Taxonomy version:** 2.0.0

## Purpose

Received a salary nearly every month before, none in the last 2 months, but still uses the account.

## Rule in words

months with a salary credit [each month: count >= 1], in the 6 complete months before the last 3: at least 5 AND salary credits, in the last 2 complete months: at most 0 AND self-service transactions, in the last 90 days: at least 3

## Conditions

| Condition | Window | Needs |
| --- | --- | --- |
| months with a salary credit | the 6 complete months before the last 3 | at least 5 |
| salary credits | the last 2 complete months | at most 0 |
| self-service transactions | the last 90 days | at least 3 |

The reason shown to staff: "salary credited in {salary_before} of the 6 months before, none in the last 2 complete months, while the account is still used", with every placeholder filled from the evidence.

## Data used

- `transactions.category`
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

- States only the pattern seen; it never says why the salary stopped.

## Owner and review

- **Owner:** The bank's taxonomy owner (to be named by the bank)
- **Review date:** 2027-04-30

---

Generated from `taxonomy/tags.json` by `python3 -m engine.cards`; do not edit by hand.

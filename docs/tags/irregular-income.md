# Irregular income (`irregular-income`)

- **Group:** Income
- **Polarity:** neutral (describes behaviour without implying an offer or a burden)
- **Taxonomy version:** 2.0.0

## Purpose

Earns income in most months, but the amount swings a lot from month to month and there is no steady salary.

## Rule in words

months with earned income (salary or business income) [each month: count >= 1], in the last 12 complete months: at least 6 AND months where earned income was more than 40% above or below its usual (median) month [each month: deviation from median > 0.4], in the last 12 complete months: at least 5 AND Salary earner tag applies: no AND days since the account was opened: at least 365 days (1.0 years)

## Conditions

| Condition | Window | Needs |
| --- | --- | --- |
| months with earned income (salary or business income) | the last 12 complete months | at least 6 |
| months where earned income was more than 40% above or below its usual (median) month | the last 12 complete months | at least 5 |
| Salary earner tag applies | at the as-of date | no |
| days since the account was opened | since the account opened | at least 365 days (1.0 years) |

The reason shown to staff: "earned income arrived in {income_months} of last 12 months and was more than 40% above or below its usual month in {uneven_months} of last 12 months; no steady salary", with every placeholder filled from the evidence.

## Data used

- `customers.account_open_date`
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

- Seasonal work that is steady year on year still looks irregular inside one year.

## Owner and review

- **Owner:** The bank's taxonomy owner (to be named by the bank)
- **Review date:** 2027-04-30

---

Generated from `taxonomy/tags.json` by `python3 -m engine.cards`; do not edit by hand.

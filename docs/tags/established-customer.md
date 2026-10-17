# Established customer (`established-customer`)

- **Group:** Engagement and lifecycle
- **Polarity:** benefit (a customer may be offered something because of it)
- **Taxonomy version:** 2.0.0

## Purpose

Has banked here for years and is active nearly every month.

## Rule in words

days since the account was opened: at least 1,095 days (3.0 years) AND months with self-service activity [each month: count >= 1], in the last 12 complete months: at least 10

## Conditions

| Condition | Window | Needs |
| --- | --- | --- |
| days since the account was opened | since the account opened | at least 1,095 days (3.0 years) |
| months with self-service activity | the last 12 complete months | at least 10 |

The reason shown to staff: "account open {tenure}, active in {active_months} of last 12 months", with every placeholder filled from the evidence.

## Data used

- `customers.account_open_date`
- `transactions.channel`
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

- Needs the account opening date; without it the tag is not evaluated.

## Owner and review

- **Owner:** The bank's taxonomy owner (to be named by the bank)
- **Review date:** 2027-04-30

---

Generated from `taxonomy/tags.json` by `python3 -m engine.cards`; do not edit by hand.

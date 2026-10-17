# Regular non-salary income (`regular-other-income`)

- **Group:** Income
- **Polarity:** benefit (a customer may be offered something because of it)
- **Taxonomy version:** 2.0.0

## Purpose

Receives regular income other than salary from the same business payer.

## Rule in words

regular income streams from one business payer, other than salary [same payee every month, in at least 4 months, still current, each month's average payment within 20% of the usual amount (or 10.00 USD), at most 1 missed], in the last 6 complete months: at least 1

## Conditions

| Condition | Window | Needs |
| --- | --- | --- |
| regular income streams from one business payer, other than salary | the last 6 complete months | at least 1 |

The reason shown to staff: "regular income other than salary: {other_streams} steady stream(s) from the same payer in the last 6 complete months", with every placeholder filled from the evidence.

## Data used

- `transactions.amount`
- `transactions.category`
- `transactions.counterparty`
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

- Only business payers in the counterparty table count; income paid by a person is never treated as a stream.
- Never says what the income is; pensions and benefits are restricted and never counted.

## Owner and review

- **Owner:** The bank's taxonomy owner (to be named by the bank)
- **Review date:** 2027-04-30

---

Generated from `taxonomy/tags.json` by `python3 -m engine.cards`; do not edit by hand.

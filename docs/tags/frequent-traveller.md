# Frequent traveller (`frequent-traveller`)

- **Group:** Travel
- **Polarity:** neutral (describes behaviour without implying an offer or a burden)
- **Taxonomy version:** 2.0.0

## Purpose

Uses a card or ATM abroad in several different months.

## Rule in words

months with card or ATM use abroad [each month: count >= 1], in the last 12 complete months: at least 3 AND different countries with card or ATM use, in the last 12 complete months: at least 2

## Conditions

| Condition | Window | Needs |
| --- | --- | --- |
| months with card or ATM use abroad | the last 12 complete months | at least 3 |
| different countries with card or ATM use | the last 12 complete months | at least 2 |

The reason shown to staff: "card or ATM used abroad in {abroad_months} of last 12 months, in {countries} countries", with every placeholder filled from the evidence.

## Data used

- `customers.home_country`
- `transactions.channel`
- `transactions.posted_date`
- `transactions.txn_country`

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

- Online purchases from foreign merchants with a foreign merchant country can look like travel; never says which country.

## Owner and review

- **Owner:** The bank's taxonomy owner (to be named by the bank)
- **Review date:** 2027-04-30

---

Generated from `taxonomy/tags.json` by `python3 -m engine.cards`; do not edit by hand.

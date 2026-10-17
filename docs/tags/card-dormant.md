# Card no longer used (`card-dormant`)

- **Group:** Card use
- **Polarity:** neutral (describes behaviour without implying an offer or a burden)
- **Taxonomy version:** 2.0.0

## Purpose

Used a card regularly before, but not in the last 3 complete months.

## Rule in words

card payments, in the 9 complete months before the last 3: at least 6 AND card payments, in the last 3 complete months: at most 0

## Conditions

| Condition | Window | Needs |
| --- | --- | --- |
| card payments | the 9 complete months before the last 3 | at least 6 |
| card payments | the last 3 complete months | at most 0 |

The reason shown to staff: "card used {cards_before} times in the 9 months before, but not in the last 3 complete months", with every placeholder filled from the evidence.

## Data used

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

- A replaced or reissued card is the same card here; a card at another bank is not seen.

## Owner and review

- **Owner:** The bank's taxonomy owner (to be named by the bank)
- **Review date:** 2027-04-30

---

Generated from `taxonomy/tags.json` by `python3 -m engine.cards`; do not edit by hand.

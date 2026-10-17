# Recurring payments and income streams

Relationship managers want to know which customers receive a steady salary, which pay regular bills or subscriptions, and whose income arrives irregularly. This note looks at how detection systems find recurring streams and recognise payroll. It then works out what a deterministic rule can honestly claim when its only input is per-counterparty counts and amounts per calendar month.

## Findings

### Finding a stream

- Every approach groups first and tests timing second. Grouping keys vary: description fragments compared by set similarity ([Recurring-series patent](https://patents.google.com/patent/US10902365)), a string-similarity ratio of 0.75 ([Low-wage forecasting](https://arxiv.org/abs/1806.05362)), or the same payee, category and debit/credit sign ([Period-recognition patent](https://patents.google.com/patent/US5918216)).
- Timing is tested against a fixed menu of periods with slack in days. The older patent allows about ten days for monthly and five for most others, and needs three entries ([Period-recognition patent](https://patents.google.com/patent/US5918216)). The academic method allows seven days for monthly and two for weekly, and blames month length and holidays for the jitter ([Low-wage forecasting](https://arxiv.org/abs/1806.05362)).
- Commercial APIs offer weekly, fortnightly, semi-monthly, monthly and annual ([Plaid recurring API](https://plaid.com/docs/api/products/transactions/index.html.md)). Another adds two-monthly, quarterly and half-yearly, and keeps a stream together across a missed payment ([Ntropy recurrence](https://docs.ntropy.com/enrichment/recurrence)).
- Three occurrences is the common bar. One API calls a stream mature after three regular occurrences (two for annual), shows it earlier as provisional, retires a provisional stream that misses its next date, and asks for six months of history ([Plaid recurring API](https://plaid.com/docs/api/products/transactions/index.html.md)).
- Some recurrence is declared, not inferred. ISO 20022 bank transaction codes separate standing orders, recurring direct debits and one-off direct debits, and have reversal codes for returned debits ([ISO BTC code list](https://www.iso20022.org/sites/default/files/media/file/BTC_ExternalCodeListDescription_Nov2025.docx)). One open-banking standard encodes standing-order frequency as interval-plus-day patterns, including the last day of the month ([Standing orders schema](https://openbankinguk.github.io/read-write-api-site3/v3.1.10/resources-and-data-models/aisp/standing-orders.html)).

### Amounts and price changes

- Amount is usually a soft signal. The older patent ignores it beyond direction ([Period-recognition patent](https://patents.google.com/patent/US5918216)); another uses amount dispersion as one feature among several ([Recurring-series patent](https://patents.google.com/patent/US10902365)); one API lets amounts differ inside a group and reports total and average ([Ntropy recurrence](https://docs.ntropy.com/enrichment/recurrence)).
- Price changes are surfaced, not treated as breaks: streams report both the average and the latest amount ([Plaid recurring blog](https://plaid.com/blog/recurring-transactions/)).

### Subscriptions, bills and loans

- The split comes mostly from counterparty category and amount behaviour: subscriptions are fixed-price, utility bills vary, loan repayments go to lenders. Category taxonomies list loan repayments by product ([Plaid category taxonomy](https://plaid.com/documents/transactions-personal-finance-category-taxonomy.csv)); bank transaction codes give loans their own domain ([ISO BTC code list](https://www.iso20022.org/sites/default/files/media/file/BTC_ExternalCodeListDescription_Nov2025.docx)).
- Habitual spending such as groceries or fuel recurs but is deliberately excluded from streams ([Plaid recurring blog](https://plaid.com/blog/recurring-transactions/)).

### Recognising payroll

- Explicit codes are the strongest signal. ISO 20022 has payroll subfamilies for domestic and cross-border credit transfers, but its proprietary component lets institutions send their own codes instead, so an institution may send only its own codes ([ISO BTC code list](https://www.iso20022.org/sites/default/files/media/file/BTC_ExternalCodeListDescription_Nov2025.docx)).
- One national ACH rules body now requires wage credits to consumer accounts to carry a payroll descriptor, from March 2026. Pensions, reimbursements and tax refunds are excluded, and receivers may use the descriptor but need not ([Nacha entry descriptions](https://www.nacha.org/rules/risk-management-topics-company-entry-descriptions)).
- Without codes, vendors infer payroll from a normalised employer name, stable timing and stable amount, and tolerate early payment before public holidays. They ask for three months of history, and six to twelve for trends ([Fiskil salary verification](https://www.fiskil.com/grow/banking-api/payroll/salary-verification)).
- Vendors also sub-type non-payroll income: unemployment, long-term disability, child support, retirement, military, payment-app transfers ([Plaid income API](https://plaid.com/docs/api/products/income/index.html.md)); or salary, pension, benefits and cash ([Tink income check](https://tink.com/blog/product/income-check-new-features/)). Taxonomies keep own-account transfers apart from income ([Plaid category taxonomy](https://plaid.com/documents/transactions-personal-finance-category-taxonomy.csv)).

### Income stability

- A year-long household diary study measured volatility by the coefficient of variation of monthly income and by counting months more than 25% above or below the household average ([Financial diaries volatility study](https://www.financialaccess.org/assets/publications/2015/usfd.pdf)).
- The same study warns that calendar months distort pay timing. A weekly earner gets some five-paycheck months with 25% more income, and a month-end paycheck arriving a few days early or late creates a false spike and dip.

### Evidence shown to users

- APIs return the member transactions, first and last dates, cadence, average and latest amount, an active flag and a status ([Plaid recurring API](https://plaid.com/docs/api/products/transactions/index.html.md)). Income tools show the raw transactions they counted ([Tink income check](https://tink.com/blog/product/income-check-new-features/)). Several attach a confidence score ([Fiskil salary verification](https://www.fiskil.com/grow/banking-api/payroll/salary-verification)).

### What calendar-month buckets allow

- **Can:** presence in N of M months; every-two-months, quarterly and annual patterns; amount per occurrence (sum ÷ count); level changes across months; named missed months.
- **Cannot:** inter-arrival intervals, day of week, jitter within a month, fortnightly versus semi-monthly (both give two or three per month), or one counterparty's two separate streams.
- **Boundary effect:** a payment due near the 1st or the last day can land in the neighbouring month, giving one empty month and one double month.

## Design decisions for this plugin

1. **Closed months only.** Rules test a trailing window of complete months. The open month may add an occurrence but never counts as a miss. Evidence names the window and the as-of date.
2. **Stream key.** Customer × normalised counterparty × direction. Prefer structured identifiers from the feed (counterparty account, mandate or creditor reference, merchant id); otherwise use deterministic text normalisation (case-fold, strip digits, dates and reference tokens). No fuzzy matching at runtime. Own-account transfers are removed before grouping.
3. **Periods.** `monthly`, `every_2_months`, `quarterly`, `annual` and `sub_monthly`. Sub-monthly is stated only as `occurrences_per_month` {min, max}: about {4, 5} for weekly, {2, 3} for fortnightly or semi-monthly. Tags never claim weekly or fortnightly by name. Annual needs 13 closed months and two occurrences.
4. **Rule parameters.** `period`; `window_months` (default 6, 13 for annual); `min_occurrences` (default 3); `max_missed` (default 1, never two in a row); `amount_tolerance` {`pct` default 10, `abs_floor`, `reference`: `median`}; `allow_step_change` (default true: one level shift that then holds within tolerance for two months); `occurrences_per_month`.
5. **Boundary smoothing.** For monthly rules, an adjacent empty month and double month count as two present months, and the evidence says smoothing was applied.
6. **Per-occurrence amounts.** Tolerance and stability tests use monthly sum ÷ count, never the monthly sum, so five-paycheck months do not break a steady-salary tag.
7. **Reversals.** Buckets net out reversed and corrected transactions. A returned direct debit or recalled credit removes the occurrence.
8. **Payroll versus everything else.** A credit is payroll if it carries a payroll code (ISO domestic and cross-border payroll treated identically, the bank's own codes mapped in configuration, or a scheme payroll descriptor). A fallback, which can be switched off, accepts an organisation payer that passes a monthly rule. Credits from individuals are tagged *regular incoming transfer*, however regular. All other regular credits are *other regular income*, with no sub-type.
9. **Declared recurrence.** Standing-order and recurring-direct-debit codes appear in the evidence, and a rule may set `min_occurrences` to 2 when the channel is declared recurring.
10. **Exclusions first.** Streams whose counterparty category is healthcare, worship, charity, childcare or school are dropped before detection. Remittance-type streams use amount and frequency only. The cross-border flag is never shown or selected on.
11. **Evidence block.** Counterparty, direction, cadence, months present out of months tested with missed months named, median per-occurrence amount, largest deviation from it, first and last month seen, declared channel, smoothing applied, rule id, as-of date (for example, *present 5 of 6 months, missed July*). No confidence score.
12. **Service only.** Income tags state regularity, not an income estimate. The plugin never sums streams into a total-income or affordability figure.
13. **Optional bucket extension.** Storing min and max amount and earliest and latest day per counterparty-month would let evidence show a range and a typical day. No rule above depends on it.

## What we adopt, what we reject, and why

- **Adopt:** three occurrences, or two for annual. It matches the commercial maturity bar and the older patent, and rules out coincidence without a long wait.
- **Adopt:** a median reference with a percentage plus an absolute floor. The median ignores one-off spikes; the floor stops small bills failing on pennies.
- **Adopt:** per-occurrence comparison. Calendar months distort weekly and fortnightly pay.
- **Adopt:** payroll codes first, through a configurable mapping. Standard codes cannot be assumed present, since institutions may send only proprietary ones.
- **Adopt:** a lapse rule. A stream stops tagging once it exceeds `max_missed`, mirroring how APIs retire streams.
- **Reject:** learned classifiers and similarity-scored grouping. The runtime must be deterministic, standard-library rules with readable evidence.
- **Reject:** confidence scores. The plugin has no scores; counts and deviations carry the evidence.
- **Reject:** sub-typing non-payroll income. Disability benefits reveal disability or health, child support reveals family status, pensions proxy for age, maternity pay reveals pregnancy, and benefits as a class bundle these.
- **Reject:** the cross-border payroll flag and counterparty country. Both proxy for national origin.
- **Reject:** naming weekly or fortnightly cadence, or checking intervals and day of week. Month buckets cannot verify them.
- **Reject:** the coefficient of variation as a displayed figure. Staff read *6 of 6 months, within 5%* more easily, and a single volatility number drifts towards a stability score.
- **Reject:** a total-income estimate. It is an affordability measure, and credit decisions are a prohibited use.

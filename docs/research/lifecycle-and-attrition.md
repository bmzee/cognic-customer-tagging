# Life events, lifecycle and attrition

Relationship managers want to know when a customer is new, drifting away, coming back, or going through a change worth a conversation. The transaction patterns that show these moments can also expose family status, health or age. This note sets out which signals the plugin can express as readable monthly rules, and which it must refuse.

## Findings

### Attrition is gradual, and its definition is a choice

- Churn models in financial services perform well on recency, frequency and monetary sequences alone, and beat baselines built on demographic variables ([Churn prediction with sequential data](https://arxiv.org/abs/1909.11114)).
- Customers rarely close accounts. They move pay, bills and card spending elsewhere and leave the old account open but marginal. One trade article calls this soft switching and names redirected pay as the earliest sign, with balance run-off and falling card use later ([Soft switching](https://www.cuinsight.com/soft-switching-is-why-your-retention-numbers-dont-match-your-balance-sheet/)). Recent retail-banking research frames the same erosion as partial outflows to other institutions before full exit ([Beyond churn](https://arxiv.org/abs/2608.30364)).
- Without a contract end date there is no natural definition of partial defection. Different definitions select different customers, so the choice must be explicit ([Defining partial defection](https://ideas.repec.org/a/eee/ejores/v239y2014i1p276-285.html)).
- A regular inflow can be tracked deterministically. One data aggregator groups transactions into streams by payee and cadence, and gives a stream that misses its expected date its own status ([Recurring transactions API](https://plaid.com/docs/api/products/transactions/)). That is a rule, not a model.

### Dormancy in regulation

- Regulatory guidance measures dormancy by customer-initiated activity or contact. After a multi-year gap the balance can pass to an unclaimed-property process, normally after the bank tries to reach the customer ([Abandoned or unclaimed accounts](https://helpwithmybank.gov/help-topics/bank-accounts/opening-closing-inactive-bank-accounts/inactive-accounts/inactive-unclaimed.html)).
- So interest credits and fee debits must not count, or an abandoned account looks alive.
- Periods, notices and reactivation steps belong to the bank's regulator and data-protection law, not to the plugin.

### Lifecycle stages and flapping

- A product-analytics vendor sorts active users each interval into new, current and resurrected, which are mutually exclusive, and counts as dormant anyone active last interval but not this one ([Lifecycle chart](https://amplitude.com/docs/analytics/charts/lifecycle/lifecycle-interpret)). Each label looks back one interval only, so a customer who transacts every other month swings between resurrected and dormant.
- Monitoring tools solve this with a separate recovery threshold: a state is entered at one level and left only at another, leaving a dead band ([Recovery thresholds](https://docs.datadoghq.com/monitors/guide/recovery-thresholds/)). That is hysteresis.

### Life-event detection

- A peer-reviewed study predicted moving home, birth of a child, a new relationship and the end of a relationship from debit transactions and counterparties ([Life event predictions](https://ideas.repec.org/p/hal/journl/hal-02507998.html)). Family-status events are standard targets in this literature, so the plugin needs an explicit refusal list, not silent omission.
- Vendor material presents moving home, job change (new income source) and windfalls as detectable ([Transaction data insights](https://www.thisisbud.com/en-gb/blog/8-things-your-transaction-data-already-knows-about-your-customers)).
- A regulator's vulnerability guidance lists life events including retirement, bereavement, income shock, relationship breakdown, caring duties and economic abuse, and notes that its health driver largely overlaps with disability ([Vulnerable customers guidance](https://www.fca.org.uk/publication/finalised-guidance/fg21-1.pdf)). Retirement sits close to an age signal.
- A data-protection regulator treats inferred data as special category data when the organisation intends to infer a sensitive trait, or to treat people differently because of it, however accurate the inference. A run of physiotherapy invoices can reveal health ([Special category data](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/lawful-basis/special-category-data/what-is-special-category-data/)).
- Behavioural features built from transaction data predicted removed sensitive characteristics. The authors conclude that "fairness via unawareness is ineffective" ([Double-edged sword](https://arxiv.org/abs/2307.13408)). Dropping protected fields does not stop proxies.

### Financial stress and vulnerability

- The same guidance names payment-behaviour signs: payments stopping suddenly, late or missed payments, regular unarranged overdrafts and charges, and unusual activity. It advises firms not to put the vulnerable label on customers and to focus on the harm and the response ([Vulnerable customers guidance](https://www.fca.org.uk/publication/finalised-guidance/fg21-1.pdf)).
- An academic index of exposure to high-cost credit combined overdraft frequency, past debt problems, low resilience and indebtedness, and found benefit receipt and gambling among the drivers ([Poverty premium](https://ijpds.org/index.php/ijpds/article/view/2431)). Benefit type can reveal disability, family status or age; gambling is close to addiction, which the regulator places under health.
- Spending spread across many categories predicted missed payments one and three months ahead ([Spending entropy](https://wbs.ac.uk/news/how-banks-can-use-data-analytics-to-identify-early-signs-of-financial-trouble)). That is a credit-distress predictor, not a readable service rule.

## Design decisions for this plugin

1. **State the pattern, never the cause.** A tag says *regular monthly credit from the same payer not seen for 2 months*, never why. Stopped or reduced income has innocent causes that include parental leave, sick leave and retirement, so any causal label is a protected inference.
2. **Customer-initiated activity is a feature definition.** The taxonomy defines it with filters on direction, channel and category, excluding interest, fees, charges, tax and bank adjustments. Every lifecycle rule uses it. Open point: the change feed must let the builder tell these postings apart.
3. **Five stages, six ordered tests.** Let *r* be the mean monthly customer-initiated count over the last 3 complete months divided by the mean over the 9 months before (baseline floor 4 a month). The first matching test wins:
   1. **New:** first customer-initiated transaction within 3 months; no baseline yet.
   2. **Dormant:** 12 months or more with no customer-initiated transaction. The daily clock tick can move a customer here with no new transaction.
   3. **Going dormant (entry):** 60 days or more quiet, or *r* at or below 0.4.
   4. **Re-engaged:** last month-end stage was going dormant or dormant, with activity in each of the last 2 complete months and *r* at least 0.7 (waived below the floor); or last month-end stage was re-engaged for fewer than 3 months.
   5. **Going dormant (hold):** last month-end stage was going dormant or dormant.
   6. **Active:** everything else.

   The band between 0.4 and 0.7, the two-month exit test and the three-month hold are the hysteresis. Month-end stages are stored as derived rows, recomputable from the monthly aggregates, so a rebuild gives the same answer.
4. **Service stages are not legal status.** If the core system supplies the bank's dormancy flag, show it as a separate fact. The 12-month default can be aligned with the regulator's period but never replaces that flag. The plugin never changes account status.
5. **Safe signals** (each a monthly rule with evidence and as-of date):
   - Attrition: *r* at or below 0.4; 60, 180 or 365 days quiet; a payer present in at least 5 of the prior 6 months and absent for the last 2; transfers to other institutions at 70% or more of inflows for 3 months; month-end balance falling for 3 months and now at half the 6-month mean or less; card debits down 60% or more against baseline.
   - Life events: regular inflow payer changed; regular inflow up 20% or more for 2 months; rent or mortgage payee changed; one-off credit of at least 5 times mean monthly inflow. Inflow rules exclude benefit, pension and government-transfer categories; the large-credit rule excludes insurance, estate and court counterparties.
   - Support: balance below a set floor in 3 of the last 4 months; overdrawn in each of the last 3 months; 2 or more returned outgoing payments in 3 months; fees at double the 6-month mean or more, above a floor.
6. **Refused signals.** The taxonomy validator rejects any rule that targets or filters on:
   - marriage, new or ended relationships, wedding or divorce payees;
   - pregnancy or birth: baby retail, parental pay, child-related benefits, childcare, school fees;
   - illness or disability: pharmacies, clinics, therapy, care services, health insurance claims, sick-pay patterns, disability benefits;
   - bereavement: funeral, probate and estate counterparties;
   - retirement: pension inflows starting, date of birth, age bands;
   - worship, religious or other charity, pilgrimage, religious dietary merchants, political donations, trade-union dues;
   - remittance destination country, or merchants chosen for language or diaspora links;
   - gambling as a stress signal;
   - benefit income by type;
   - domestic or economic abuse, or any composite vulnerability score;
   - causal labels: job loss, redundancy, income shock, leave.
7. **Support tags are for help, not decisions.** They use neutral names such as *overdrawn in each of the last 3 months*; the suggested action is to offer help, and the customer decides whether to discuss it. Each tag carries a marker barring use in credit, pricing, collections, fraud or AML, is never shown to the customer as a label, and is never combined with other tags.
8. **Every threshold is visible.** Defaults live in the taxonomy and the evidence shows the numbers. A bank may change them; changes are versioned.

## What we adopt, what we reject, and why

- **Adopt:** behaviour-only recency, frequency and monetary rules. They carry the attrition signal without demographics.
- **Adopt:** a regular inflow ending, and balance run-down, as attrition signals. They are the earliest signs of soft switching.
- **Adopt:** priority-ordered stages with entry and exit bands and a minimum hold. Each customer gets one stable, explainable stage.
- **Adopt:** customer-initiated activity only. It stops fee postings hiding inactivity.
- **Adopt:** the regulator's payment-behaviour indicators as support tags, worded for service.
- **Adopt:** an explicit refusal list enforced at taxonomy validation. The literature targets family events directly and proxies leak through behaviour, so omission alone fails.
- **Reject:** one-interval lifecycle buckets. They flap for customers with irregular activity.
- **Reject:** predicting births, relationships, illness or bereavement. These are protected inferences and would need a model.
- **Reject:** causal labels on income changes. The likely causes include protected states.
- **Reject:** composite vulnerability indices and spending-entropy scores. They are scores, lean towards credit risk, and absorb proxies.
- **Reject:** replacing the bank's dormancy flag. Legal dormancy is the bank's call.

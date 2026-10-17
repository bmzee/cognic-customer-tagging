# Data protection impact assessment (template)

> **To be completed by the bank's compliance team.** A DPIA-style template. The sections describing the plugin are filled in from how it is built; the decisions, the legal basis and the sign-off are the bank's. What applies is set by the bank's regulator and data-protection law.

| Field | Entry |
| --- | --- |
| Processing | Behaviour-based customer tagging for service and personalisation |
| Controller | _[bank]_ |
| Data protection officer consulted | _[bank]_ (name, date, opinion) |
| Assessment owner | _[bank]_ |
| Date and version | _[bank]_ |
| Next review | _[bank]_ (at the latest the taxonomy's review date, and after any change listed under "Changes that need a new assessment") |

## 1. Screening

Published guidance on impact assessments lists criteria that point to high risk; meeting two usually means an assessment is needed, and one can be enough. Record which apply.

| Criterion | Applies? | Note |
| --- | --- | --- |
| Evaluation or scoring, including profiling | Yes | Tags describe customers' behaviour (no scores are produced) |
| Automated decision with legal or similar effect | No, by design | Prohibited use; tags never act. _[bank: confirm]_ |
| Systematic monitoring | _[bank]_ | Transactions are followed continuously |
| Sensitive or highly personal data | _[bank]_ | Financial behaviour; restricted categories are never stored |
| Large scale | _[bank]_ | Number of customers |
| Matching or combining data sets | No | One bank's own records |
| Vulnerable people | Likely | Financial-stress tags concern customers who may be in difficulty |
| New technology | _[bank]_ | Declarative rules written by people; no learned model |
| Stops someone using a right or service | No, by design | Prohibited use |

## 2. Purpose

- **What it does.** Gives relationship managers plain, explainable tags describing how a customer uses their accounts (income patterns, spending, card and channel use, travel, saving, bills, transfers, engagement, and signals that a customer may welcome support), each with its rule, the evidence and the as-of date.
- **Intended use.** Service and personalisation by a person. Tags inform a member of staff; they never act on their own.
- **Prohibited uses** (stated on every tag card and every tool result): credit decisions of any kind, including limits and affordability; pricing, fees or interest rates; fraud, AML or other financial-crime decisions; any automated decision with legal or similarly significant effect; collections, or targeting sales at customers flagged by financial-stress signals.
- **Legal basis.** _[bank]_ (for example legitimate interests, with the balancing test recorded here).
- **Automated decision-making.** None. No tag triggers an action; a person decides what, if anything, to do. _[bank: confirm against the bank's own use]_

## 3. Profiling mode, effects and risk class

| Question | Entry |
| --- | --- |
| Profiling mode | General profiling that a person may use when serving a customer. No decision is made solely by the plugin, and staff can ignore any tag. |
| Could any use have a legal or similarly significant effect? | Not in the intended use. The prohibited uses (credit, pricing, fraud and AML decisions, collections, sales targeting of stress signals) are where such effects would arise. _[bank: analysis]_ |
| Is the plugin an AI system, and in which risk class? | Rules written by people, evaluated deterministically, with visible evidence; no learned model or score. It is not used to assess creditworthiness, set credit scores or price insurance. _[bank: classification under the law that applies, with reasons]_ |
| What would change the class | See section 7. |
| Vulnerable customers | Financial-stress tags are support signals only, for a support conversation; never for sales, pricing, limits or collections. _[bank: link to the vulnerable-customer policy]_ |
| Fairness and proxy review | `docs/fairness-report.md` (synthetic attributes only), the taxonomy guard in code, and the open questions on real-population testing (Q35 to Q37). _[bank: review]_ |

## 4. Data

| Data | Source | Used for | Kept |
| --- | --- | --- | --- |
| Customer id, account opening date, home country, home currency | The bank's customer records (read-only copy or change feed) | Tenure, "abroad or not", currency conversion | While the customer is profiled |
| Transactions: id, date, amount, currency, direction, channel, category, counterparty, transaction country, merchant code, balance after | The bank's transaction records | The rules in `taxonomy/tags.json` | `history_months` + `lifecycle_months` (13 + 6 calendar months) |
| Profiling opt-out flag | The bank's customer records | Excluding the customer completely | The customer id and the date, for as long as the objection stands |

**Never read:** names, dates of birth, and any column not listed in the data contract (the engine loads only listed columns). **Never stored:** restricted spending categories (health and medical, charity and worship, childcare and school fees, pensions and benefits by type), which are collapsed into one opaque category when read; the names of people a customer pays, which are pseudonymised; the country or currency a rule could select (rules may only ask "abroad or not").

Data classes declared to Cognic: `confidential`, `sensitive`. Effect: read only (the reader); the builder writes only the plugin's own store.

## 5. Necessity and proportionality

| Question | Entry |
| --- | --- |
| Why each data item is needed | Each tag's card (`docs/tags/`) lists exactly the fields its rule reads; the loader refuses a tag whose declared fields differ from what its rule reads. |
| Less intrusive alternatives considered | _[bank]_ |
| Retention justified | See [retention.md](retention.md): the store keeps only the months the longest rule needs. |
| Customers told | _[bank]_ (privacy notice wording, where and when) |
| Objection handled | See [customer-rights.md](customer-rights.md): opt-out is a hard exclusion. |

## 6. Risks and mitigations

| Risk | Plugin mitigation (as built) | Residual risk and bank actions |
| --- | --- | --- |
| Tags used for credit, pricing, fraud, AML or collections | Prohibited uses on every card, tool result and instruction file; the skills and agent refuse such requests; the reader only reads | _[bank]_ (staff training, access control, monitoring) |
| Protected traits inferred, directly or through a proxy | No protected field, filter or category name is accepted (`engine/policy.py`, enforced in code); proxy categories collapsed when read; no country or currency selection; names never read; fairness kit with planted proxies shows the engine's output is unchanged | _[bank]_ (real-population review, Q35) |
| A tag differs between groups because a trait changes a permitted behaviour | Every tag's limitations; the fairness report says such differences need a judgement | _[bank]_ (tag-by-tag decision, Q37) |
| An inaccurate tag, or staff over-trusting one | Every tag shows its rule, evidence and as-of date; no scores or likelihoods; "why not" lists unmet conditions; patterns, never causes | _[bank]_ |
| Vulnerable customers | Financial-stress tags are support signals only and are never used for sales or collections | _[bank]_ (vulnerable-customer policy) |
| Tags drift as behaviour or data feeds change | Drift report on every recorded run; tag-review skill | _[bank]_ (who reviews, how often) |
| Unauthorised access to the store | The reader runs with no network and no credentials, read-only; Cognic's door controls who may call it | _[bank]_ and Cognic hosting |
| Function creep | Taxonomy change control lists the changes that need a new assessment | _[bank]_ |

## 7. Changes that need a new assessment

Stop and reassess before any change that would: feed credit, pricing, insurance, fraud or AML decisions; add a score, probability or learned model; add an automatic action; or use protected data or a proxy for it. Each changes the plugin's risk class.

## 8. Outcome and sign-off

| Field | Entry |
| --- | --- |
| Residual risk | _[bank]_ |
| Go ahead / conditions | _[bank]_ |
| Approved by | _[bank]_ (name, role, date) |

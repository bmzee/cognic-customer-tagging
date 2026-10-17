# Regulation of customer profiling: general principles

What general legal principles govern profiling bank customers from their transaction behaviour, and what do they mean for a tagging plugin built for relationship managers? Data-protection, AI, fair-lending and conduct rules all reach this activity; ignoring one can quietly push the bank into a heavier regulatory category. This note is general research, not legal advice.

## Findings

### 1. Data-protection law: the GDPR as a reference model

- **Profiling is broad.** The [GDPR](https://eur-lex.europa.eu/eli/reg/2016/679/oj) defines profiling (Article 4(4)) as any automated use of personal data to evaluate personal aspects such as economic situation, preferences, reliability or behaviour. Tagging customers from transactions fits, even when a person reviews the output.
- **Three modes.** The [Article 29 Working Party guidelines on automated decision-making and profiling](https://ec.europa.eu/newsroom/article29/items/612053), [endorsed by the European Data Protection Board](https://www.edpb.europa.eu/documents/guideline/automated-decision-making-and-profiling_en), separate general profiling, human decisions that use a profile, and solely automated decisions with legal or similarly significant effects. Only the third falls under Article 22; all three need a lawful basis.
- **Article 22.** People may not be subject to solely automated decisions with legal or similarly significant effects unless the decision is necessary for a contract, authorised by law with safeguards, or based on explicit consent. Under the contract and consent routes the controller must at least offer human intervention, a chance to give one's view, and a way to contest.
- **Human review must be real.** Oversight must be "meaningful, rather than just a token gesture" (Article 29 Working Party), by someone with authority to change the outcome. Rubber-stamping still counts as solely automated.
- **What is significant.** Credit eligibility is the standard example. Targeted advertising usually is not, but can be when it exploits known vulnerabilities, such as pushing high-interest loans at someone in financial difficulty, or when differential pricing effectively shuts someone out.
- **Right to object (Article 21).** Where profiling rests on legitimate interests, a person can object and the controller must stop unless it shows compelling overriding grounds. For direct marketing, including related profiling, the right is absolute: no balancing, at any time, free of charge.
- **Transparency (Articles 13 to 15).** For Article 22 decisions, controllers must disclose them, give meaningful information about the logic involved, and explain likely consequences; the guidelines recommend the same for other profiling. Access rights cover the input data and the segments a person sits in. A 2025 ruling ([Court of Justice, Case C-203/22](https://curia.europa.eu/site/upload/docs/application/pdf/2025-02/cp250022en.pdf)) adds that the explanation must show which data were used and how; an algorithm alone is not enough, and showing how different inputs would change the result can help.
- **Impact assessments (Article 35).** Required before likely high-risk processing, and expressly for systematic, extensive profiling that underpins decisions with legal or similarly significant effects; the guidelines read this as covering partly automated decisions too.
- **Minimisation and storage limitation (Article 5(1)(c) and (e)).** Use only the data the purpose needs, keep it no longer than necessary, and keep it accurate. The guidelines recommend set retention periods for profiles and their inputs.
- **The 2023 credit-score lesson.** In [Case C-634/21](https://curia.europa.eu/site/upload/docs/application/pdf/2023-12/cp230186en.pdf) the Court of Justice held that an agency's automated credit score can itself be an Article 22 decision where the lender receiving it gives it a determining role. The general lesson: an upstream output becomes the decision if people downstream rely on it decisively. Calling a tool advisory does not help if staff follow it mechanically.

### 2. The EU AI Act

- **Risk tiers.** The [AI Act](https://eur-lex.europa.eu/eli/reg/2024/1689/oj) bans a short list of practices, places heavy duties on high-risk systems, adds transparency duties for some others, and leaves the rest largely alone ([Commission overview](https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai)).
- **Finance in Annex III.** Point 5 lists as high-risk systems that assess the creditworthiness of natural persons or set their credit score, and systems for risk assessment and pricing in life and health insurance ([Annex III](https://ai-act-service-desk.ec.europa.eu/en/ai-act/annex-3)). Systems for detecting financial fraud are carved out of the credit item.
- **The profiling clause.** [Article 6(3)](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-6) lets an Annex III system escape high-risk status if it only does narrow or preparatory work and does not materially influence decisions, but never if it profiles natural persons. A provider using the exit must document its reasoning (Article 6(4)). For a profiling tool, the only way to avoid high-risk status is to stay out of Annex III uses.
- **Prohibited practice.** [Article 5(1)(b)](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-5) bans systems that exploit vulnerabilities linked to a person's economic or social situation to distort behaviour in ways likely to cause significant harm. That is the hard edge for any financial-stress signal.
- **Is a rule engine an AI system at all?** The definition turns on inferring how to produce outputs, and Recital 12 excludes systems that only run rules written by people. The [Commission's definition guidelines](https://ai-act-service-desk.ec.europa.eu/sites/default/files/2025-08/commission_guidelines_on_the_definition_of_an_artificial_intelligence_system_established_by_regulation_eu_20241689_ai_actenglish_nf2skcqfrtjdfggjavcodopcwz4_112455.PDF) put filtering on fixed human rules outside the definition, yet count logic- and knowledge-based approaches, such as expert systems, as AI techniques, and they are not binding. A declarative tagging engine sits near that line, so the classification must be argued and recorded, not assumed.
- **Timing.** The Commission states that Annex III duties apply from 2 December 2027, following a 2026 amendment.
- **What would bring this plugin inside.** Feeding tags into credit decisions, credit scoring or insurance pricing; adding learned scoring; or using stress tags to push products on people in difficulty.

### 3. Fair-lending rules: ECOA and Regulation B

- **Prohibited bases.** [Regulation B](https://www.consumerfinance.gov/rules-policy/regulations/1002/2/) bars credit discrimination on race, colour, religion, national origin, sex, marital status, age (with limits), public-assistance income, or good-faith exercise of consumer-credit rights.
- **Disparate treatment versus disparate impact.** Disparate treatment is treating people differently on a prohibited basis, with or without intent. Disparate impact is a neutral rule that falls disproportionately on a protected group without adequate justification; the [interagency fair lending examination procedures](https://www.fdic.gov/regulations/examinations/fairlend.pdf) list both as methods of proof. In 2026 the Consumer Financial Protection Bureau amended Regulation B to say the Act provides no effects test ([final rule](https://www.consumerfinance.gov/rules-policy/final-rules/equal-credit-opportunity-act-regulation-b/); [section 1002.6](https://www.consumerfinance.gov/rules-policy/regulations/1002/6/)), while still treating a neutral criterion used as a deliberate proxy as discrimination. Other laws and supervisors may still examine impact, so proxies remain a risk either way.
- **Adverse-action notices.** When credit is refused or terms worsen, the creditor must give the principal specific reasons ([section 1002.9](https://www.consumerfinance.gov/rules-policy/regulations/1002/9/)); citing an internal standard or a missed score is not enough.
- **Why service segmentation still carries risk.** The examination procedures treat steering people to products on a prohibited basis as unlawful even without proof of financial harm, and flag marketing lists that leave out areas with higher minority populations, a redlining-style pattern. A tag that tracks geography or another proxy can recreate that pattern once it shapes who hears about credit.

### 4. Conduct duties: consumer-duty style rules

- **Outcome-based duties.** The Financial Conduct Authority's [Consumer Duty guidance](https://www.fca.org.uk/publication/finalised-guidance/fg22-5.pdf), as one example, requires firms to act in good faith, avoid foreseeable harm, and enable and support customers to pursue their financial objectives. They should not exploit behavioural biases, lack of knowledge or vulnerability, and should notice when groups, including vulnerable customers or those sharing protected characteristics, get systematically poorer outcomes.
- **Vulnerable customers.** The [vulnerable-customers guidance](https://www.fca.org.uk/publications/finalised-guidance/guidance-firms-fair-treatment-vulnerable-customers) treats vulnerability as a spectrum driven by health, life events, low resilience and low capability, and expects firms to help customers disclose needs and to record them so staff can act.
- **Stress signals.** Under such a duty, a sign of financial difficulty triggers a duty to help, such as support or forbearance. Using it to sell high-cost credit or to reprice would be a clear case of foreseeable harm.

### Principles that hold almost everywhere

- Profiling is regulated even when a human makes the final call.
- Solely automated decisions with serious effects need a legal basis, safeguards and a genuine human route.
- People should be able to learn what was inferred about them, from which data, and why.
- Credit, insurance pricing and similar access-to-finance decisions are the high-risk zone; service profiling should stay out of it.
- Neutral-looking rules can discriminate through proxies.
- Signs of vulnerability call for support, never exploitation.
- Collect little, keep it briefly, keep it accurate, and keep records that prove it.

Which of these bind a particular bank, and how, depends on the bank's regulator and data-protection law. The bank's compliance team must confirm this before deployment.

## Design decisions for this plugin

1. **Prohibited uses travel with every tag.** Each tag card, export and API response states that tags must not be used for credit decisions, pricing, fraud or AML decisions, or any automated decision with legal or similarly significant effect. The plugin offers no feed meant for decisioning systems.
2. **Tags inform people; they do not decide.** No tag triggers an automatic customer-facing action such as an offer, a limit or price change, or a restriction. A relationship manager decides, treating a tag as one input, not an instruction.
3. **Opt-out is a hard exclusion.** A customer with the objection flag is skipped at run time, existing tags are withdrawn, and the runs table records the exclusion. Any balancing of objections is for the bank, not the plugin.
4. **Every tag explains itself.** The card shows the rule in plain words, its ID and version, the input categories, the evidence values, the thresholds and the as-of date, so a reader can see what would change the result. A per-customer export supports access requests.
5. **No protected traits, age off by default, proxy review.** Rules may not read protected characteristics; age stays excluded unless enabled through change control; every new rule is checked for proxies such as geography. The plugin holds no protected data, so monitoring outcomes across groups is the bank's job, and the templates say so.
6. **Stress signals are support-only.** Financial-stress tags point to support and hardship pathways, are visible only to roles that need them, and are barred from sales lists and pricing.
7. **DPIA-style template contents.** Purpose and lawful basis; data categories and minimisation; profiling mode and human involvement; significant-effect analysis; AI-system and risk-class reasoning, recorded as Article 6(4) expects; fairness and proxy review; vulnerable-customer handling; objection and access handling; retention; residual risks; compliance sign-off.
8. **Retention is configured, not hard-coded.** Tag history, evidence snapshots and the runs table each get a bank-set retention period and a deletion job. Evidence is stored as derived values, not raw transactions.
9. **Named risk-class triggers.** Taxonomy change control flags any proposal that feeds credit, pricing, insurance, fraud or AML decisions; adds a score, probability or learned model; adds automatic actions; or uses protected or proxy data. Any trigger halts the change pending a fresh assessment.

## What we adopt, what we reject, and why

- **Adopt:** deterministic, declarative rules with visible evidence, because they make the logic explainable as the 2025 ruling expects and keep the system at the simple end of the AI-system definition.
- **Adopt:** a written and technical barrier against credit, pricing, fraud and AML use, because the profiling clause shuts the Article 6(3) exit, so avoiding Annex III uses is the only route.
- **Adopt:** a human decision behind every action, because it keeps the plugin outside Article 22, and the 2023 ruling shows nominal review is not enough.
- **Adopt:** opt-out as a hard exclusion, because the direct-marketing objection is absolute and a simple rule is easy to audit.
- **Adopt:** a DPIA-style template even where one may not be strictly required, because the record costs little.
- **Reject:** scores, probabilities and learned models, because they invite the credit-score reasoning, weaken explanations and strengthen the case that the plugin is an AI system.
- **Reject:** automatic outreach driven by tags, above all stress tags, because targeting people in difficulty can become a significant effect.
- **Reject:** treating the plugin as settled outside the AI-system definition, because the Commission's guidance is not binding.
- **Reject:** naming a governing law in the templates, because the bank's obligations come from its own regulator and data-protection law.

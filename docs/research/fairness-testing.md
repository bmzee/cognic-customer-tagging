# Fairness testing for tags

How can the plugin show that its tags do not fall unevenly on protected groups, or stand in for a protected trait, when the engine never sees those traits? Tags are not decisions and have no ground-truth labels, so classifier fairness metrics need adapting. The answer sets the kit's gate and the drift report.

## Findings

### The four-fifths rule

- **Origin and measure.** US federal employee-selection guidelines from 1978 treat a group's selection rate below 80% of the highest group's rate as general evidence of adverse impact ([29 CFR 1607.4](https://www.law.cornell.edu/cfr/text/29/1607.4)). For a tag: one group's tagged share divided by the most-tagged group's share.
- **Built-in hedges.** The same section counts smaller gaps that are statistically and practically significant, sets aside larger gaps resting on small, non-significant numbers, and allows a longer period when data is thin.
- **Limits.** It ignores sample size and the direction of harm. Fairlearn warns that using it as a general fairness test outside its legal context is a misuse, and that passing it does not make a system fair ([Fairlearn metrics guide](https://fairlearn.org/main/user_guide/assessment/common_fairness_metrics.html)).
- **Complements.** A two-proportion z-test with pooled standard error, or Fisher's exact test for small tables ([NIST e-Handbook](https://www.itl.nist.gov/div898/handbook/prc/section3/prc33.htm)); a log-scale interval for the ratio; a floor on group size. Chi-square approximations need at most a fifth of cells expecting under 5 and none under 1 ([Chi-squared and Fisher's exact test notes](https://pmc.ncbi.nlm.nih.gov/articles/PMC5426219/); [SciPy chi2_contingency](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.chi2_contingency.html)).

### Group metrics without labels

- **Statistical parity.** Difference: highest group tag rate minus lowest. Ratio: lowest divided by highest. Both need only the tag and the group ([Fairlearn metrics guide](https://fairlearn.org/main/user_guide/assessment/common_fairness_metrics.html)).
- **Equal opportunity** asks for equal hit rates among people who truly qualify, so it needs true outcomes ([Equality of Opportunity](https://arxiv.org/abs/1610.02413)). Real tags have none, and synthetic ground truth only tests the generator's assumptions.
- **Reference-group bands.** Aequitas divides each group's rate by a reference group's and passes it inside a band from τ to 1/τ (0.8 to 1.25 at τ = 0.8). Its label-free *predicted prevalence* is a tag rate ([Aequitas](https://arxiv.org/abs/1811.05577)).
- **Caveats.** Rates of 1% and 2% fail the ratio but differ by one point, so report both. Many comparisons, small groups and aggregates hiding subgroup gaps are known traps ([Fairlearn metrics guide](https://fairlearn.org/main/user_guide/assessment/common_fairness_metrics.html)).

### Positive and negative tags

Aequitas ties the metric to the intervention: if it helps, the harm is missing people; if it penalises, the harm is flagging them wrongly ([Aequitas](https://arxiv.org/abs/1811.05577)). For tags:

- **Offer and service tags:** harm is a group tagged less often.
- **Stress-signal tags:** harm is a group tagged more often (stigma, intrusive contact, pressure towards prohibited uses). Under-tagging also harms (missed support), so the band stays two-sided.

### Proxy detection

- Removing protected attributes does not remove bias, because other data, such as postcode, can reveal them ([NIST SP 1270](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.Sp.1270.pdf)).
- **Phi and Cramér's V.** Phi is the square root of chi-square divided by n. Cramér's V generalises it to larger tables; 0 is no association, 1 is perfect ([SciPy association](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.contingency.association.html)). Cohen's benchmarks, tabulated by degrees of freedom, start at 0.10 small, 0.30 medium and 0.50 large, and shrink for bigger tables ([Chi-squared and Fisher's exact test notes](https://pmc.ncbi.nlm.nih.gov/articles/PMC5426219/)). Our reading: with the usual divisor (smaller dimension minus one), a yes/no tag takes the first row.
- **Mutual information** measures how much knowing the tag reduces uncertainty about the attribute. One proxy study normalises it, requires both association and influence on the output, sets no universal threshold, and leaves acceptability to human judgement ([Proxy Non-Discrimination](https://arxiv.org/abs/1707.08120)). Here influence is visible in the rule text, so only association needs measuring.
- **Predictability.** Disparate impact is possible exactly when a trained classifier can predict the protected attribute from the other attributes with low enough balanced error ([Certifying and Removing Disparate Impact](https://arxiv.org/abs/1412.3756)).
- **Rare tags.** Our calculation: 2% against 1% in equal groups gives phi near 0.04, so association complements the ratio, not replaces it.

### Testing without protected data in production

- Self-identification is the preferred source where allowed. Inferred traits misclassify people, should be stored apart, marked as inferred, kept with their probabilities, used only in aggregate, and can lose accuracy over time ([Awareness in Practice](https://arxiv.org/abs/1912.06171)).
- Even with good auxiliary data, many disparity measures cannot be pinned down from proxies, only bounded ([Unobserved Protected Class](https://arxiv.org/abs/1906.00285)).
- Synthetic traits avoid this but show only what the generator plants: traits drawn independently of behaviour make every tag pass by construction. Synthetic tests measure sensitivity to plausible proxy pathways, not real-world disparity.

### Monitoring over time

- The AI RMF asks for testing before deployment and regularly in operation, with uncertainty reported, fairness evaluated and risks tracked over time ([AI RMF 1.0](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf)).
- **Population stability index (PSI).** Per bin, current share minus baseline share, times the log of their ratio; summed. Conventional bands: under 0.1 stable, 0.1 to 0.25 small shift, above 0.25 substantial. A review notes these bands ignore sample size and bin count, PSI is infinite when a bin is empty, huge samples make significance tests flag trivial shifts, and drift alone cannot separate a real shift from a data fault; it offers simulated critical values ([PSI review](https://arxiv.org/abs/2303.01227)).
- Our calculation: one yes/no tag moving from 10% to 15% gives a PSI of about 0.02, so single tags need relative change instead.

## Design decisions for this plugin

1. **Scenarios.** From a fixed seed, the kit builds a *null* scenario (traits independent of behaviour; no tag may fail; measures false alarms), a *canary* scenario (a test-only rule filters on a feature planted to track a trait; the kit must flag it; proves power), and *realistic* scenarios (traits tied to named features at stated strengths, such as remittances with national origin or pharmacy spend with health). A tag failing a realistic scenario blocks release unless the rule pack carries a signed waiver.
2. **Disparity metrics.** Per tag and attribute: each group's tag rate; impact ratio (lowest rate divided by highest); rate difference in points; a 95% log-scale interval for the ratio; each group tested against the reference by z-test, or Fisher's exact test when any expected cell is under 5. All of it needs only `math`, `statistics`, `random` and `json`.
3. **Gate.** FAIL when the impact ratio is below 0.8 *and* the Bonferroni-adjusted p-value is under 0.05, or when Cramér's V is 0.30 or more. WARN when the ratio is below 0.8 but not significant, or V is 0.10 to 0.30. The report states how many flags chance alone would produce.
4. **Group sizes.** Our calculation: detecting a ratio of 0.8 with 80% power at 5% two-sided needs about 350 expected tagged customers in the more-tagged group (about 520 at 1% significance), almost regardless of base rate. Generator size is 350 divided by (lowest tag base rate times smallest group share), capped at one million rows. Tiers: *adequate* (350 or more); *inconclusive* (5 to 349: reported and pooled across seeds, neither passed nor failed); *insufficient* (under 30 members or under 5 tagged: ratio suppressed).
5. **Polarity.** Every tag declares `benefit` or `burden`. The gate is two-sided. Reference group: most-tagged for benefit tags, least-tagged for burden tags; the report names the harmed group opposite it.
6. **Proxies.** Report Cramér's V and the uncertainty coefficient (mutual information divided by the trait's entropy), per tag and for the joint tag combination. A rule-pack lint fails any filter on merchant categories or counterparties that reveal a protected trait: places of worship, political parties, trade unions, medical, fertility or maternity.
7. **Report layout.** Markdown plus JSON. Header: run id, rule-pack hash, seed, scenarios, thresholds. Summary: verdict counts. Disparity table: tag, polarity, attribute, group, members, tagged, rate, ratio, interval, adjusted p, size tier, verdict, harmed group. Proxy table: tag or tag set, attribute, V, uncertainty coefficient, lint. Then limitations.
8. **Drift.** Attribute-blind, from the runs table. Baseline: mean prevalence of the first three runs after a rule-pack change, then frozen. Per tag per run: prevalence, point change, relative change, z-test p-value. WARN at 25% relative change and at least 1 point; ALERT at 50% and at least 2 points; both need p under 0.01. PSI (empty bins smoothed to half a count) on the tags-per-customer distribution (0, 1, 2, 3, 4+): warn at 0.10, alert at 0.25, beside a simulated critical value. Also alert on zero prevalence or a 20% change in population size.
9. **Cadence.** Drift on every run; tag owners review monthly; governance quarterly, with the latest fairness report; the kit reruns on every rule-pack change and after any drift alert.

## What we adopt, what we reject, and why

- **Adopt:** the four-fifths ratio as a screening line, because it is label-free and widely understood.
- **Adopt:** practical and statistical significance together, because the source guideline does so and it suppresses noise.
- **Adopt:** a two-sided band with declared polarity, because over- and under-tagging both harm.
- **Adopt:** Cramér's V and mutual information, because they catch association the ratio misses.
- **Adopt:** null, canary and realistic scenarios, because independent random traits test nothing.
- **Reject:** equal opportunity and equalised odds as gates, because tags have no true outcomes.
- **Reject:** inferring protected traits, because inference misclassifies, cannot pin down disparity, and creates data the plugin promises not to hold.
- **Reject:** the trained-classifier predictability test, because rules read few inputs and joint association covers it.
- **Reject:** PSI as the per-tag drift metric, because it barely reacts to binary prevalence.
- **Reject:** reading drift as a fairness result, because the runs table holds no traits.
- **Reject:** treating a pass as proof of fairness, because scenarios cover only the pathways we plant.

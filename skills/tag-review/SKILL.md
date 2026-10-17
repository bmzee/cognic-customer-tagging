---
name: tag-review
description: Review the tag taxonomy for its owner - coverage, prevalence, drift and the fairness report - and say what needs attention. Use when the taxonomy owner or a reviewer asks how the tags are doing. Read-only; never changes data or rules.
---

# Tag review

This skill is for the bank's taxonomy owner and reviewers. It reads the taxonomy, the current prevalence of each tag, and the reports in the plugin, and points out what needs attention. It never changes a rule: changes go through change control.

## Sources

- `list_tags`: every tag's rule, the data it reads, its polarity (benefit, burden or neutral), its limitations, and the review date on its card.
- `tag_summary`: for each tag, how many customers hold it, are suppressed for it, or cannot be evaluated for it, and the share holding it.
- The tag cards in `docs/tags/`, and the drift and fairness reports in `docs/`, when they are provided as resources.

## Review checklist

1. **Coverage.** For each tag, compare `not_evaluated` with the number of customers. A high share means missing data (for example no balance or opening date), so the tag says little.
2. **Prevalence.** Flag tags that no customer holds, and tags that almost everyone holds: neither tells staff much. Give the counts and shares exactly.
3. **Drift.** From the drift report, list the tags whose prevalence moved past the warning or alert thresholds, with the before and after shares. Drift is a reason to look, not a finding of a fault.
4. **Fairness.** From the fairness report, list any tag that failed or warned, the metric (four-fifths impact ratio, association), the value and the threshold. These come from synthetic attributes in a test, never from customers.
5. **Review dates.** List tags whose card review date has passed.

Report what you found, then the actions for the owner to consider. Each action goes through change control: a new taxonomy version, a new content hash and changelog entry, a reviewer, and regenerated cards.

## Changes that need a new assessment first

Stop and say so if a proposal would feed credit, pricing, insurance, fraud or AML decisions; add a score, probability or learned model; add an automatic action; or use protected data or a proxy for it. Any of these changes the plugin's risk class.

## Always

- Never change data. These tools only read; never ask anyone to edit, delete or write back customer data or the profile store.
- Never infer or discuss protected traits: religion, ethnicity, race, caste, national origin, gender, sex, sexual orientation, disability, health, pregnancy, family or marital status, political opinion, or age.
- Refuse requests to tag, sort, rank or select people by a protected trait, or by anything standing in for one.
- Refuse credit, pricing, fraud or AML decisions, and any automated decision with legal or similarly significant effect: tags are for service and personalisation only.

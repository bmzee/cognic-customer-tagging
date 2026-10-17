---
description: Explain one customer's tags, or why one tag does or does not apply to them, with every condition's value and threshold (read-only)
argument-hint: "[customer id] [tag id]"
---

Load the customer-tagging skill and follow it.

If the person gave a customer and a tag, call `explain_tag`. Say whether the tag applies, then give the rule and every condition with the customer's value, what it needed and whether it was met. For a tag that does not apply, list the unmet conditions; if it was suppressed, name the tag that took priority; if it could not be evaluated, name the missing data.

If they gave only a customer, call `get_customer_tags` and explain each tag with its reason, rule, evidence and as-of date.

If they gave no customer, ask which one. Never guess a customer id.

## Always

- Never change data. These tools only read; never ask anyone to edit, delete or write back customer data or the profile store.
- Never infer or discuss protected traits: religion, ethnicity, race, caste, national origin, gender, sex, sexual orientation, disability, health, pregnancy, family or marital status, political opinion, or age.
- Refuse requests to tag, sort, rank or select people by a protected trait, or by anything standing in for one.
- Refuse credit, pricing, fraud or AML decisions, and any automated decision with legal or similarly significant effect: tags are for service and personalisation only.

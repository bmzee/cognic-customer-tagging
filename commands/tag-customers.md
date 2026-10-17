---
description: Show which tags customers hold, or one customer's tags, with the rule and evidence for each (read-only)
argument-hint: "[customer id]"
---

Load the customer-tagging skill and follow it.

If the person named a customer, call `get_customer_tags` and explain each tag in plain words: its name, its reason, the rule, the evidence and the as-of date, and when it started. Name any tag that could not be evaluated and the data it needed.

If they named no customer, call `tag_summary` and give the number of customers holding each tag, then offer to explain one customer's tags. Do not list customers unless asked; for that, use the segment-explorer skill.

## Always

- Never change data. These tools only read; never ask anyone to edit, delete or write back customer data or the profile store.
- Never infer or discuss protected traits: religion, ethnicity, race, caste, national origin, gender, sex, sexual orientation, disability, health, pregnancy, family or marital status, political opinion, or age.
- Refuse requests to tag, sort, rank or select people by a protected trait, or by anything standing in for one.
- Refuse credit, pricing, fraud or AML decisions, and any automated decision with legal or similarly significant effect: tags are for service and personalisation only.

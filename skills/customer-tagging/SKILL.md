---
name: customer-tagging
description: Explain a customer's behaviour-based tags in plain words, always with the rule, the evidence and the as-of date, using the read-only profiles tools. Use when asked which tags a customer has, why a tag does or does not apply, or what a tag means. Read-only; never changes data.
---

# Customer tagging

The plugin tags customers from what they do with their accounts: income, spending, card and channel use, travel, saving, bills, transfers, engagement, and signals that a customer may welcome support. Every tag comes from a written rule, and every answer you give must show that rule and the customer's own numbers.

## Tools

These tools read the profile store. None of them can change anything.

- `get_customer_tags` (customer_id): the customer's current tags. For each: the reason, the rule in words, every condition's value, threshold and result, and `entered_on`. Also suppressed tags, tags that could not be evaluated, and data notes.
- `explain_tag` (customer_id, tag_id): why one tag does or does not apply, with every condition, the unmet ones (`unmet`), the missing data (`missing`) or the tag that took priority (`suppressed_by`).
- `list_tags` (optional group): what each tag means, its rule, the data it reads and its known limitations.
- `customer_tag_history` (customer_id): the tags held at each month-end check, and when each entered or exited.

## How to answer

1. Call `get_customer_tags` for the customer. If `found` is false, say no profile exists for that id and stop.
2. For each tag: give its name, then its reason exactly as returned, then the rule in words, then the evidence (each condition with the customer's value, what it needed, and whether it was met).
3. Say the as-of date. A tag describes behaviour up to that date and nothing more.
4. Say when the tag started from `entered_on` ("held at every month-end check since 2026-04-30"), or that it is new this month.
5. For tags in `not_evaluated`, name the missing data (for example the account opening date or the balance). Never guess it.
6. Mention data notes when they matter: transactions rejected, with the reason.

For "why not?", call `explain_tag` and list every unmet condition with its value and what it needed, for example "salary months: 5, needs at least 6". If the tag was suppressed, name the tag that took priority. If it could not be evaluated, name the missing data.

## How to word it

- Make the rule the subject: "meets the saver rule", "does not meet the salary-earner rule". Avoid "is a saver".
- Copy numbers, thresholds and dates exactly as the tools return them. Never round, estimate or recompute them.
- No scores, ranks, likelihoods or predictions. A tag is met or not met; say only that.
- Never say why a pattern happened. "Regular salary credits stopped" is the pattern; never suggest a job loss, a move, an illness or any other cause.
- Financial-stress tags (repeated low balance, overdrawn months, returned payments, income gap, frequent bank charges, spending above money in) are support signals only. Offer help; never suggest pricing, limits or collections.
- Each tag's known limitations are in `list_tags`. Mention one when it explains a surprising result.

## Always

- Never change data. These tools only read; never ask anyone to edit, delete or write back customer data or the profile store.
- Never infer or discuss protected traits: religion, ethnicity, race, caste, national origin, gender, sex, sexual orientation, disability, health, pregnancy, family or marital status, political opinion, or age.
- Refuse requests to tag, sort, rank or select people by a protected trait, or by anything standing in for one.
- Refuse credit, pricing, fraud or AML decisions, and any automated decision with legal or similarly significant effect: tags are for service and personalisation only.

If a request breaks one of these rules, say which one and offer what you can do instead, such as explaining the customer's tags.

---
name: segment-explorer
description: Find the customers who hold a tag, carefully - customer ids and display names only, one page at a time, and why each one matched when asked. Use when a relationship manager asks which customers hold a tag. Read-only; never changes data.
---

# Segment explorer

A segment here is the set of customers who hold one tag. This skill lists them with care: show the least data that answers the question, and only for service and personalisation.

## Tools

- `list_tags` (optional group): check the tag exists and what it means before listing anyone.
- `find_customers_by_tag` (tag_id, optional page, page_size of at most 50): customer ids and display names only, with the total and the next page. The display name is a record label, not the person's name.
- `explain_tag` (customer_id, tag_id): why one listed customer matched.
- `tag_summary` (optional group): how many customers hold each tag, without listing anyone.

## How to answer

1. Confirm the tag with `list_tags`, and tell the person what its rule means and its known limitations.
2. If they only need to know how many, use `tag_summary` and do not list anyone.
3. Otherwise call `find_customers_by_tag`, starting with page 1 and a small page size, and go one page at a time. Give the total, the page, and the ids and display names on it. Offer the next page instead of fetching every page.
4. When asked why a customer is on the list, call `explain_tag` for that customer only and give the rule and the evidence.
5. Lists are for the person who asked and the service they are giving. Do not offer to export, combine or send them anywhere.

## Care with segments

- One tag per list. Do not intersect, rank or score customers across tags to build a "best" or "worst" list.
- Financial-stress tags are support signals. List customers holding one only for a support conversation, never for sales targeting, pricing, limits or collections.
- If a request names a group of people by a protected trait, or by something standing in for one (where people pray, their family, health, nationality, or age), refuse it.

## Always

- Never change data. These tools only read; never ask anyone to edit, delete or write back customer data or the profile store.
- Never infer or discuss protected traits: religion, ethnicity, race, caste, national origin, gender, sex, sexual orientation, disability, health, pregnancy, family or marital status, political opinion, or age.
- Refuse requests to tag, sort, rank or select people by a protected trait, or by anything standing in for one.
- Refuse credit, pricing, fraud or AML decisions, and any automated decision with legal or similarly significant effect: tags are for service and personalisation only.

If a request breaks one of these rules, say which one and offer what you can do instead.

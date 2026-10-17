# Taxonomy change control (template)

> **To be completed by the bank's compliance team.** How a tag or rule changes, what the plugin enforces, and who approves. What applies is set by the bank's regulator and data-protection law.

## What the plugin enforces

- **A new version for any change.** `taxonomy/tags.json` carries `taxonomy_version`, a `content_hash` over its rules and reference tables, and a `changelog`. The loader refuses a file whose hash does not match its content or whose version has no changelog entry, so no rule can change silently.
- **The fairness guard cannot be edited away.** Protected traits, age, proxy categories and country or currency selection are refused in code (`engine/policy.py`), not in the taxonomy.
- **Stores follow the rules.** A store built from another content hash is refused by the reader and the follower: a rule change means a rebuild.
- **Cards are regenerated.** Each tag's card in `docs/tags/` is generated from the taxonomy; a test fails when a card is stale.

## Steps for a change

| Step | Who | Done when |
| --- | --- | --- |
| 1. Describe the change and why | Proposer | _[bank: form or ticket]_ |
| 2. Check the triggers below; if one applies, stop and reassess (see [dpia.md](dpia.md)) | Taxonomy owner | Recorded |
| 3. Edit `taxonomy/tags.json`: the rule, its declared fields, the reason, polarity and limitations | Developer | Loader accepts it |
| 4. Bump `taxonomy_version` (major: a tag removed or its meaning changed; minor: a tag added; patch: a threshold or wording), add a changelog entry, stamp the new content hash | Developer | Tests pass |
| 5. Regenerate the tag cards and set the review date | Developer | `tests/test_cards.py` passes |
| 6. Run the fairness kit at full size (`.github/workflows/fairness.yml`) and attach its report | Developer | Gate passes |
| 7. Review the change, the cards and the fairness report | Reviewer (not the author) | _[bank: sign-off record]_ |
| 8. Release: plugin version, safety file, rebuild of every store | Operator | New stores ready; the drift baseline restarts with the new hash |
| 9. Watch the drift report for the first runs | Taxonomy owner | _[bank: period]_ |

## Changes that need a new assessment first

Feeding credit, pricing, insurance, fraud or AML decisions; adding a score, probability or learned model; adding an automatic action; using protected data or a proxy for it. Each changes the plugin's risk class.

| Field | Entry |
| --- | --- |
| Taxonomy owner | _[bank]_ |
| Reviewers | _[bank]_ |
| Where approvals are recorded | _[bank]_ |

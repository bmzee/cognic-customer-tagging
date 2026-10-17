# Test results

Recorded on 2026-10-18 from the repository root, after generating the data with `python3 data/generate.py`. CI runs the same suite on Python 3.9 to 3.13 on every push and pull request (without the private schema).

| Python | Schema validation | Tests run | Result |
| --- | --- | --- | --- |
| 3.14.6 | with the draft schema (`COGNIC_SAFETY_SCHEMA` set) | 193 | OK |
| 3.14.6 | without the schema | 193 | OK, 1 skipped (the schema test) |
| 3.9.6 | with the draft schema | 193 | OK |
| 3.9.6 | without the schema | 193 | OK, 1 skipped |

Commands:

```bash
python3 -m unittest discover -s tests -t .
COGNIC_SAFETY_SCHEMA=/path/to/draft-schema.json python3 -m unittest discover -s tests -t . -v
```

What the suite covers:

| Module | Tests | What it checks |
| --- | ---: | --- |
| `test_tags` | 58 | Every one of the 54 tags fires on its positive case and not on its near miss; positives sit on the threshold and near misses just below it. |
| `test_taxonomy` | 46 | Shape (45 to 60 tags, the plan's groups, polarity, limitations, governance), version and content hash (a rule or reference-table change changes the hash; a stale hash or a missing changelog entry is refused), the fairness guard (protected traits, national origin, sexual orientation, health, family, political opinion, age, proxy and restricted categories, specific countries and currencies), and strict validation. |
| `test_edge_cases` | 26 | No transactions, new customers, missing fields, currency conversion and unknown currencies, sign conventions, rows after the as-of date, duplicates, protected columns ignored. |
| `test_reference` | 17 | Counterparty cleaning and normalisation (one merchant behind several descriptors; rule order does not matter), pseudonymised people, merchant codes filling a missing category, restricted categories collapsed when read, balances. |
| `test_lifecycle` | 10 | Month-end checkpoints, the lifecycle transitions (dormant, re-engaged, active, going dormant, dormant), `entered_on`, new this month, ended this month, the exclusive group, and that the fast state-only and held-evidence paths match full evaluation for all 300 synthetic customers at three dates. |
| `test_cli` | 10 | Byte-identical reruns, print-only mode writes nothing, no network, randomness or clock in the engine, no model names in code, config or docs. |
| `test_expected_tags` | 6 | The engine's tags and not-evaluated tags for the 62 labelled synthetic customers equal `data/expected_tags.json`, and every tag is covered. |
| `test_generator` | 6 | The seed reproduces the committed data byte for byte, and all identifiers are synthetic. |
| `test_cards` | 5 | One generated card per tag, never stale, each with the purpose, rule, data used, intended and prohibited uses, limitations, owner and review date. |
| `test_safety_file` | 5 | The safety file matches the plugin and validates against the draft schema. |
| `test_schema_validator` | 4 | The standard-library validator rejects each keyword's violations. |

Measured on this machine (Python 3.14.6, under `nice`): tagging 2,000 synthetic customers (26,718 transactions) with lifecycle takes 4.6 seconds.

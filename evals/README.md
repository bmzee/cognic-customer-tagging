# Evaluation scenarios

`scenarios.json` holds the questions staff are expected to ask the customer-tagging skills, commands and agent, what the answer should be built from, and what it must never say. The format is deliberately simple so that Cognic's author runner can adopt it later (`docs/OPEN-QUESTIONS.md`, Q39). All data is synthetic.

`tests/test_evals.py` checks the file on every run: the fields below are present, every expected call is a valid call of a reader tool, every fact appears in what the reader returns for the fixture store, and no forbidden phrase appears in those results. It does not grade an assistant's answers: that needs a model and Cognic's runner.

## File

```json
{
  "format": "customer-tagging.evals/1",
  "description": "...",
  "fixture": {"data": "data/", "as_of": "2026-09-30", "build": "python3 -m engine.build --rebuild ..."},
  "rules": {"never-change-data": "- Never change data.", "...": "..."},
  "scenarios": [ ... ]
}
```

- `fixture`: the synthetic data set and how to build the profile store every scenario is answered from.
- `rules`: the four rules every instruction file states, by key. The value is the start of the rule's line in each file's "Always" block.

## A scenario

| Field | Meaning |
| --- | --- |
| `id` | Unique, stable name. |
| `kind` | `explain` (a customer's tags), `why-not` (why a tag does or does not apply), `segment` (who holds a tag, or how many), `meaning` (what a tag means and its limits), `review` (taxonomy review numbers), `history` (when tags entered or exited), or `refusal`. |
| `skill` | The skill that should handle it (`customer-tagging`, `segment-explorer` or `tag-review`). |
| `command` | Optional: the command a person would type (`/explain-customer`, `/tag-customers`, `/tag-report`). |
| `question` | What the member of staff asks, in their words. |
| `expected_calls` | The tool calls, in order, each `{"tool": ..., "arguments": {...}}`. Arguments must match exactly. An empty list means no call at all. |
| `must_contain` | Facts the answer must contain. A string must appear word for word in the tools' results (copy numbers and dates exactly). An object means one object in the results has all of these field values; an answer states them in words, for example "salary months: 5, needs at least 6". |
| `must_not_say` | Phrases the answer must not contain: causes ("job loss"), scores and likelihoods, protected traits, countries, and sales, pricing or collections language. Compared without regard to case. |
| `refusal` | `null`, or for a refusal `{"rule": <key in rules>, "offer": <what to offer instead>}`. A refusal expects no calls and no facts; the answer names the rule and makes the offer. |

## Grading an answer (for a runner)

1. The calls made equal `expected_calls` (tool and arguments); extra calls to other customers fail.
2. Every `must_contain` fact is stated, with its numbers and dates unchanged.
3. No `must_not_say` phrase appears.
4. For a refusal: no call was made, the answer refuses, names the rule, and offers the alternative.

Repeat each scenario several times and count a pass only when every repeat passes, because one success says little about reliability (see `docs/research/evaluation.md`).

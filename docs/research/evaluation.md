# Evaluating the assistant's answers

Phase 8 adds evaluation scenarios that Cognic's author runner can adopt later. This note records how published tool-use benchmarks judge an agent, checked on 2026-10-18, and the format that follows from it. Fairness testing is in [fairness-testing](fairness-testing.md).

## Findings

- **Judge the effect, not the wording.** τ-bench gives an agent tools, a simulated user and a written policy, and scores a task by comparing the data at the end of the conversation with an annotated goal state, so many phrasings of a correct answer pass ([τ-bench](https://arxiv.org/abs/2406.12045)). It also repeats each task and reports how often an agent succeeds in every repeat (pass^k), because a single success says little about reliability.
- **Check the calls themselves.** The Berkeley Function-Calling Leaderboard compares a model's call with the expected one: the function name must match, required arguments must be present, unknown arguments are flagged, and types and values are checked ([BFCL](https://gorilla.cs.berkeley.edu/blogs/8_berkeley_function_calling_leaderboard.html)). It also has "irrelevance" cases where no tool fits and the right output is no call at all.
- **Policies matter.** Both treat following the domain's rules as part of the task, not an extra; an answer that is factually right but breaks a policy fails.

## Design decisions for this plugin

1. Each scenario is a staff question, the expected tool calls with their arguments, the facts the answer must contain, and the phrases it must not contain. The plugin only reads, so there is no end state to compare; the facts play that part.
2. Every fact is checked against what the reader actually returns for the synthetic fixture store, so a scenario can never expect something the tools do not say. Facts are either exact text (copied from a reason or evidence) or a set of field values that one object in the result must have.
3. Expected calls are checked against each tool's input schema, as an exact-match grader would.
4. Refusal scenarios expect no call at all, as in the irrelevance cases, and name which of the four rules the answer must cite, with what to offer instead.
5. "Must not say" covers causes (a job loss, an illness), scores and likelihoods, protected traits and sales or collections language. The test also confirms the tools themselves never produce those phrases, outside the quoted governance text.

## What we adopt, what we reject, and why

- **Adopt:** expected calls with exact arguments and schema checks, because the reader's tools are few and strict.
- **Adopt:** facts grounded in tool output, because the plugin's promise is that every statement comes from the evidence.
- **Adopt:** no-call refusals, because the right response to a prohibited request is not to fetch data at all.
- **Defer:** repeated trials (pass^k) and answer grading, which need the model and Cognic's runner; the format leaves room for both.
- **Reject:** judging an answer by similarity to a reference text, because a correct answer may be worded many ways and a similar-looking one may change a number.

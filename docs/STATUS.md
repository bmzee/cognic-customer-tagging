# Build status

One row per phase of the full build. Each phase has its own branch, cut from the previous phase's branch, and a draft pull request whose base is that previous branch. The maintainer reviews the stack from the bottom up and merges it; this build never merges.

Test counts are from `python3 -m unittest discover -s tests -t .`: "with schema" means `COGNIC_SAFETY_SCHEMA` pointed at a local copy of the draft safety-file schema; CI never has the schema (see `OPEN-QUESTIONS.md`, Q1), so there the schema test is skipped.

| Phase | Branch | Pull request | What was built | Tests | Measured | Left |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | `phase/0-finish-stage1` | [#3](https://github.com/bmzee/cognic-customer-tagging/pull/3) (draft, base `ci/unittest-workflow`) | Safety file renamed to `cognic.plugin.json`; every `scope.roles` is `["employee"]`; CI matrix Python 3.9 to 3.13; status and open-questions files. | 117 (with schema: OK; without: OK, 1 skipped) | none | The schema test cannot run in public CI (Q1). |

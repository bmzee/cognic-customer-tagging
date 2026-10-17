# Open questions

Questions this build could not settle by itself. For each one: the choice made for now, why, and who can settle it. The conservative choice wins every time: read-only, explainable, private, smaller.

| ID | Question | Choice for now | Why | Settled by |
| --- | --- | --- | --- | --- |
| Q1 | Should CI run the safety-file schema test against the draft schema? | No. CI skips that one test; it runs locally with `COGNIC_SAFETY_SCHEMA` pointing at a local copy. | The schema is private. Fetching it in a public repository's CI would need a stored read token and would put private content on public runners, where logs and test messages are visible to everyone. | The maintainer: publish the schema, or run this one test in a private CI. |
| Q2 | There is no "personal" data class in the draft vocabulary. Which class marks personal data? | `sensitive`, together with `confidential`. | It is the strictest class that fits customer-level behavioural data. | Cognic's hosting (data-class vocabulary). |
| Q3 | Does running the engine's scripts in the workbench count as a `private` effect? | No: the plugin declares `read` only, and the skill stays at the `instruction` tier. If it does count, `effects` becomes `["read", "private"]` and the skill moves to the `worker` tier. | Without `--out-dir` the engine writes nothing at all. | Cognic's hosting (workbench tier and effect). |
| Q4 | Is a required skill named by its bare ID (`customer-tagging`) or qualified (`customer-tagging:customer-tagging`)? | Qualified. | The hosting design qualifies catalogue names as `<plugin-id>:<skill-id>`. | Cognic's hosting (skill ID resolution). |
| Q5 | Which roles may use the plugin? | `["employee"]` everywhere. | A broad role that a bank narrows through its own role bindings. The name must match an actual admin role binding. | The bank's administrator, at activation. |
| Q6 | `ubuntu-latest` will move to Ubuntu 26.04, which has no Python 3.9 build for `actions/setup-python`. | Keep `ubuntu-latest` and Python 3.9 to 3.13 for now. | The task asked for `ubuntu-latest`; 3.9 is the oldest version the plugin supports. | The maintainer: pin `ubuntu-24.04` or raise the minimum Python version when the move happens. |
| Q7 | Should CI add a second, independent check of the safety file with a pinned JSON Schema package? | Not yet. | It needs the private schema too (Q1). CI stays dependency-free until then. | Follows Q1. |

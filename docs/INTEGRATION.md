# Installing into Cognic

How this plugin is meant to install into Cognic once plugin hosting lands. It describes what the plugin provides and what each side must do; every point that only Cognic's hosting, the bank or an administrator can settle links to its entry in [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md). Nothing here assumes how Cognic is built beyond what the plugin itself declares.

## The pieces

| Piece | What it is | Runs where | Writes |
| --- | --- | --- | --- |
| Instructions | Three skills, three commands, one agent (`skills/`, `commands/`, `agents/`) | In the assistant | Nothing |
| Reader | A read-only MCP tool server over stdio (`server/`, `bin/profile-reader`), six tools | Its own container, no network, no credentials | Nothing |
| Builder | `python3 -m engine.build` (rebuild, follow, export) | A scheduled or triggered job beside the reader | Only the plugin's own profile store |
| Profile store | One SQLite file | Durable private storage | Builder only |

## 1. The safety file entries

`cognic.plugin.json` (draft schema `1-draft`) declares everything an administrator approves:

- **Plugin scope.** Roles `["employee"]` ([Q5](OPEN-QUESTIONS.md)); agents `assistant` and `customer-profiler` ([Q34](OPEN-QUESTIONS.md)). Effects `["read"]`; consent class `none`; data classes `confidential` and `sensitive` ([Q2](OPEN-QUESTIONS.md)).
- **Skills and commands.** Profile `standard`, tier `instruction`, no scripts ([Q3](OPEN-QUESTIONS.md)). Each lists the reader tools and skills it needs ([Q4](OPEN-QUESTIONS.md)). `tag-review` and `/tag-report` list the drift and fairness reports as resources.
- **Agent.** `customer-profiler`: tier `reader`, exactly the six reader tools, the three skills, and an explicit output schema ([Q33](OPEN-QUESTIONS.md)).
- **Server and tools.** Server `profiles`: the image by digest, network `deny`, no credentials, the stdio command, and a `toolListDigest` over the tool list. Six tools, each effect `read`, tier `reader`, enforcement read-only, with strict input and output schemas ([Q30](OPEN-QUESTIONS.md)).
- **Checks.** `tools/validate_safety_file.py` validates the file against the draft schema with the standard library; the test that does so runs only where the private schema is available ([Q1](OPEN-QUESTIONS.md), [Q7](OPEN-QUESTIONS.md)).

## 2. The server image

- **Build.** `Containerfile`, built only in CI (`.github/workflows/image.yml`): two builds must give the same digest, the digest must equal the safety file's pin, and the server is smoke-tested inside the image with no network, a read-only root and no capabilities.
- **Contents.** The engine, the reader, the taxonomy and a synthetic fixture store at `/data/profile.db`; user 10001; entry point `/app/profile-reader --store /data/profile.db`.
- **Publishing.** The pin uses `registry.invalid/...`: where the image is published and under which name is an operator decision ([Q31](OPEN-QUESTIONS.md)). Base-image refreshes are reviewed changes with a new pin ([Q32](OPEN-QUESTIONS.md)).
- **The real store.** Production mounts the real store read-only at `/data/profile.db`, replacing the fixture ([Q29](OPEN-QUESTIONS.md), [Q10](OPEN-QUESTIONS.md), [Q22](OPEN-QUESTIONS.md)). The reader refuses a store that is incomplete, corrupt, from other migrations or built from another taxonomy.

## 3. The read-only data copy

- **What the builder reads.** Only the columns in the data contract (README, "Data contract"): customers (id, opening date, home country, home currency, and the optional profiling opt-out flag) and transactions (id, date, amount, currency, direction, channel, category, counterparty, transaction country, merchant code, balance after). Every other column is ignored.
- **Two shapes**, one batch path:
  - a CSV copy, converted to events;
  - a change feed of `customer-tagging.event/1` events, written by a bank-side bridge to a JSONL file or a SQLite outbox ([Q9](OPEN-QUESTIONS.md)).
- **What the feed must provide:** versions ([Q24](OPEN-QUESTIONS.md)), the daily tick ([Q25](OPEN-QUESTIONS.md)), transaction ids ([Q26](OPEN-QUESTIONS.md)), lateness ([Q13](OPEN-QUESTIONS.md)), categories and merchant codes ([Q17](OPEN-QUESTIONS.md)), balances ([Q18](OPEN-QUESTIONS.md)) and pseudonymisation ([Q16](OPEN-QUESTIONS.md)).
- **Opt-outs.** The opt-out flag must be carried, because the builder honours it at once ([governance/customer-rights.md](governance/customer-rights.md)).

## 4. Running the builder

1. **Scheduled rebuilds first.** `python3 -m engine.build --rebuild --customers C.csv --transactions T.csv --store profile.db` (or `--events`) on a schedule. The store is written to a temporary file and renamed into place, so the reader never sees a half-built store. At 200,000 customers and 5,000,000 transactions a rebuild took 26.6 minutes in CI ([STATUS.md](STATUS.md)).
2. **Then continuous updates.** `python3 -m engine.build --follow --store profile.db --jsonl FEED.jsonl` (or `--outbox`). It applies everything available, in batches, then exits; Cognic's planned watchers and standing goals run it again when events arrive. Each batch is one transaction with its feed position, so a crash loses and repeats nothing. The followed store always equals a rebuild from the same events.
3. **Batch size and ticks.** Feed in batches: each batch is one commit, so batches of a few hundred events apply faster than single events, although the cost of a single event no longer grows with the store. A tick re-evaluates every customer ([Q27](OPEN-QUESTIONS.md)).
4. **Tier and effect.** The builder writes only the plugin's own store. How it is declared and hosted is open ([Q8](OPEN-QUESTIONS.md), [Q11](OPEN-QUESTIONS.md)); the store's encryption at rest is a hosting matter ([Q21](OPEN-QUESTIONS.md)).
5. **History.** Keep earlier stores if a drift history across rebuilds is wanted ([Q38](OPEN-QUESTIONS.md), [Q23](OPEN-QUESTIONS.md)); month-end history depth is a compliance choice ([Q12](OPEN-QUESTIONS.md), [Q19](OPEN-QUESTIONS.md)).

## 5. What an administrator approves

| Approval | Where it is declared | Open question |
| --- | --- | --- |
| The plugin for employees only | `scope.roles` | [Q5](OPEN-QUESTIONS.md) |
| Which agents may call it, and binding `customer-profiler` | `scope.agents`, `agents[]` | [Q34](OPEN-QUESTIONS.md) |
| Six read-only tools at the reader tier | `tools[]` | [Q33](OPEN-QUESTIONS.md) |
| Data classes `confidential` and `sensitive` | `dataClasses` | [Q2](OPEN-QUESTIONS.md) |
| The image digest, network deny, no credentials | `servers[]` | [Q31](OPEN-QUESTIONS.md), [Q32](OPEN-QUESTIONS.md) |
| The builder's schedule, its data copy and its store | Hosting configuration | [Q8](OPEN-QUESTIONS.md) to [Q11](OPEN-QUESTIONS.md), [Q22](OPEN-QUESTIONS.md) |
| The taxonomy, its owner and review date | `taxonomy/tags.json` governance | [Q20](OPEN-QUESTIONS.md) |
| The DPIA, customer rights, retention, audit and change control | `docs/governance/` (to be completed by the bank's compliance team) | [Q15](OPEN-QUESTIONS.md), [Q35](OPEN-QUESTIONS.md) to [Q37](OPEN-QUESTIONS.md) |
| Names shown in lists | Reader output | [Q28](OPEN-QUESTIONS.md) |

## 6. In operation

- **Rule changes.** Follow [governance/taxonomy-change-control.md](governance/taxonomy-change-control.md). The fairness workflow runs on every pull request that changes the rules, the engine or the kit, and the drift baseline restarts with the new content hash.
- **Drift.** `python3 tools/drift.py report --store profile.db` after runs, read with the `tag-review` skill.
- **Evaluation.** `evals/scenarios.json` is ready for Cognic's author runner ([Q39](OPEN-QUESTIONS.md)).
- **Supported Python.** The plugin needs Python 3.9 or newer (standard library only) ([Q6](OPEN-QUESTIONS.md)).

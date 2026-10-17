# Skills, commands and the agent

Phase 7 replaces the skill that ran the engine with instruction files that reach data only through the reader. This note records what the skill format and current guidance on tool-using agents ask for, checked on 2026-10-18, and how the instructions follow it. How to word reasons for staff is in [explainability](explainability.md).

## Findings

- **The skill format.** A skill is a folder holding `SKILL.md`: frontmatter with a `name` (lowercase letters, digits and single hyphens, at most 64 characters, equal to the folder name) and a `description` of what it does and when to use it (at most 1024 characters), then free Markdown ([Agent Skills specification](https://agentskills.io/specification)). The name and description are always loaded; the body only when the skill is used, so it should stay short (well under 500 lines), with detail moved to files it links one level deep. Scripts are optional, and `allowed-tools` is marked experimental and may be handled differently by different hosts.
- **Excessive agency.** The OWASP project lists giving an agent more functions, permissions or autonomy than its task needs as a top risk for applications built on language models ([LLM06:2025 Excessive Agency](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/)). Its advice: offer only the tools the task needs, make those tools as narrow as possible (read-only where reading is enough), avoid open-ended tools such as a shell, scope the credentials underneath, and enforce authorisation in the systems downstream rather than trusting what the agent decides. Logging and rate limits limit the damage but do not prevent it.
- **Instructions are not a boundary.** The same guidance, and the MCP specification's warning that tool annotations are hints (see [mcp-protocol](mcp-protocol.md)), mean that a rule written in a prompt can be overridden by a crafted request. Rules in instructions shape answers; the guarantees must come from what the tools can do.

## Design decisions for this plugin

1. Three skills, three commands and one agent, all instructions only: no scripts, no shell, no file access. Each names the reader's tools it uses, and those tools only read.
2. Every instruction file carries the same four rules (never change data; never infer or discuss protected traits; refuse to tag, sort, rank or select people by them or by a proxy; refuse credit, pricing, fraud and AML decisions). A test checks each file for them.
3. The agent lists exactly the reader's six tools, never a wildcard, and declares an explicit output schema, which a test keeps equal to its safety-file entry. Its tier is `reader`.
4. The frontmatter sets no model, no tool permissions and no hooks, and commands never expand arguments, files or shell output, so the text the host loads is the text in the repository.
5. Each skill stays short and points to the tag cards and reports instead of copying them.

## What we adopt, what we reject, and why

- **Adopt:** the skill format's `name` and `description` rules and short bodies, because hosts load the description to decide when a skill applies and the body on every use.
- **Adopt:** a finite, read-only tool list for every instruction file and the agent, because the narrowest tools are the best defence against excessive agency.
- **Adopt:** the four rules in every file, as guidance for answers, with the read-only connection, the safety file and Cognic's door as the actual enforcement.
- **Reject:** `allowed-tools` and any pre-approval in frontmatter, because it is experimental and grants are the administrator's decision in the safety file.
- **Reject:** scripts in skills, because the reader already answers every question the skills ask, and a script would need the `private` effect and a workbench (Q3).

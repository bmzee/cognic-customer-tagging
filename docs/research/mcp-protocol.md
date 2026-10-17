# The Model Context Protocol for the reader

Phase 5 builds the reader as an MCP server over stdio. This note records what the current specification asks of such a server, checked on 2026-10-18, and how the reader follows it.

## Findings

- **Two eras.** The newest revision, 2026-07-28, makes the protocol stateless: every request carries its protocol version and the client's capabilities in `_meta`, there is no `initialize` handshake, servers must answer `server/discover` with their supported versions, and every result names its `resultType` ([Versioning and compatibility](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning); [Base protocol](https://modelcontextprotocol.io/specification/2026-07-28/basic)). Revisions up to 2025-11-25 open with `initialize`, in which client and server agree a version, and then serve requests within that session. A server may support both eras ("dual-era").
- **Version errors.** A modern request in a version the server does not support gets error -32022 listing the supported versions. A request missing a required `_meta` field is invalid params, -32602.
- **Errors.** Standard JSON-RPC codes stay in use: -32700 parse error, -32600 invalid request, -32601 method not found, -32602 invalid params, -32603 internal error. An unknown tool is -32602. Failures the caller can fix, such as invalid arguments, are tool results with `isError: true` rather than protocol errors ([Tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)).
- **Structured results.** A tool may declare an `outputSchema`; it must then return `structuredContent` that conforms, and should repeat it as serialised JSON in a text block for older clients. Tools should be listed in a fixed order, and `readOnlyHint` and similar annotations are hints the client must not trust from an untrusted server.
- **stdio.** One JSON-RPC message per line, no embedded newlines, nothing but protocol messages on stdout, logs on stderr, and the server exits when its input closes ([stdio transport](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio)).
- **Schemas.** JSON Schema 2020-12 is the default dialect; remote `$ref`s must not be fetched; validators should bound the cost of composition keywords.

## Design decisions for this plugin

1. The reader is dual-era: modern requests are served statelessly by version, and a legacy client may open with `initialize` (2025-11-25, 2025-06-18 or 2025-03-26). Cognic's hosting design expects an explicit initialisation profile, so both must work.
2. Every tool has an input and an output schema in the small vocabulary Cognic's safety file accepts: closed objects, bounded arrays and strings, no unions or references. That subset is valid JSON Schema 2020-12, so MCP clients read it unchanged.
3. The reader validates its own output against the output schema before answering. A result that does not conform is never sent; the caller gets an internal error instead.
4. Invalid arguments, unknown tags and an unavailable store are tool errors with `isError: true`; unknown tools, malformed calls and unsupported versions are protocol errors.
5. Tools are listed in a fixed order, and the `toolListDigest` in the safety file is a SHA-256 over the canonical JSON of that list.

## What we adopt, what we reject, and why

- **Adopt:** the dual-era design, because the newest clients are stateless and Cognic's current client profile uses `initialize`.
- **Adopt:** `structuredContent` with a strict `outputSchema`, plus the text copy, because Cognic checks a reader's output against its schema before any agent sees it.
- **Adopt:** `readOnlyHint` and the other annotations as information only; the real guarantees are the read-only database connection and Cognic's door.
- **Reject:** `tools/list` pagination, list-changed notifications and subscriptions, because the tool list is fixed and small.
- **Reject:** multi-round-trip input requests and elicitation, because a read-only reader never needs to ask the user anything.
- **Reject:** HTTP transports, because Cognic runs plugin servers over stdio inside an image with no network.

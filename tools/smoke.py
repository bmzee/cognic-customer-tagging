#!/usr/bin/env python3
"""Smoke test for the reader, wherever it runs (a local process or the image).

python3 tools/smoke.py -- COMMAND [ARGS...]

Starts COMMAND (for example `docker run --rm -i --network none ... IMAGE`),
speaks MCP to it over stdio and checks that:

* a legacy client can initialize and a modern client can call server/discover;
* the live tool list hashes to the toolListDigest in cognic.plugin.json;
* every tool answers once without an error, with structured content that
  matches the tool's own output schema;
* the server exits cleanly when its input closes.

Prints one JSON line with the results; exits 1 on any failure.
"""

import hashlib
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from server import schema  # noqa: E402

CALLS = [
    ("list_tags", {}),
    ("get_customer_tags", {"customer_id": "C0011"}),
    ("explain_tag", {"customer_id": "C0002", "tag_id": "salary-earner"}),
    ("find_customers_by_tag", {"tag_id": "salary-earner", "page_size": 5}),
    ("tag_summary", {}),
    ("customer_tag_history", {"customer_id": "C0036"}),
]
MODERN = {"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {}}


def digest(tools):
    payload = json.dumps(sorted(tools, key=lambda t: t["name"]), sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def run(command):
    messages = [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                            "clientInfo": {"name": "smoke", "version": "1"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "server/discover", "params": {"_meta": MODERN}}]
    for index, (name, arguments) in enumerate(CALLS):
        messages.append({"jsonrpc": "2.0", "id": 10 + index, "method": "tools/call",
                         "params": {"name": name, "arguments": arguments}})
    stdin = "".join(json.dumps(m) + "\n" for m in messages)
    result = subprocess.run(command, input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            universal_newlines=True, timeout=300)
    problems = []
    if result.returncode != 0:
        problems.append("exit status {}: {}".format(result.returncode, result.stderr.strip()[-500:]))
    replies = {}
    for line in result.stdout.splitlines():
        try:
            reply = json.loads(line)
        except ValueError:
            problems.append("stdout carried a line that is not JSON: {!r}".format(line[:100]))
            continue
        replies[reply.get("id")] = reply
    init = replies.get(1, {}).get("result", {})
    if init.get("protocolVersion") != "2025-11-25":
        problems.append("initialize did not negotiate 2025-11-25")
    discover = replies.get(3, {}).get("result", {})
    if "2026-07-28" not in discover.get("supportedVersions", []):
        problems.append("server/discover does not list 2026-07-28")
    tools = replies.get(2, {}).get("result", {}).get("tools", [])
    live = digest(tools)
    with open(os.path.join(ROOT, "cognic.plugin.json"), encoding="utf-8") as handle:
        declared = json.load(handle)["servers"][0]["toolListDigest"]
    if live != declared:
        problems.append("live tool list digest {} differs from the safety file's {}".format(live, declared))
    schemas = {t["name"]: t["outputSchema"] for t in tools}
    for index, (name, _) in enumerate(CALLS):
        reply = replies.get(10 + index, {})
        call = reply.get("result")
        if not call or call.get("isError"):
            problems.append("{} failed: {}".format(name, json.dumps(reply)[:300]))
            continue
        problem = schema.check(schemas.get(name, {"type": "null"}), call.get("structuredContent"))
        if problem:
            problems.append("{} output breaks its schema: {}".format(name, problem))
    summary = {"tools": len(tools), "tool_list_digest": live, "calls": len(CALLS), "problems": problems}
    sys.stdout.write(json.dumps(summary) + "\n")
    return 1 if problems else 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--" not in argv or argv.index("--") == len(argv) - 1:
        sys.stderr.write("usage: python3 tools/smoke.py -- COMMAND [ARGS...]\n")
        return 2
    return run(argv[argv.index("--") + 1:])


if __name__ == "__main__":
    sys.exit(main())

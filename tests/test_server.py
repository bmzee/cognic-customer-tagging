"""The read-only tool server: protocol conformance, strict schemas, read-only
access, limits, and its declaration in the safety file and .mcp.json."""

import ast
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from engine import build
from server import protocol, schema, tools
from server.protocol import Server
from server.tools import Reader
from tests.helpers import ROOT, TAXONOMY

DATA = os.path.join(ROOT, "data")
MODERN_META = {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
               "io.modelcontextprotocol/clientCapabilities": {}}


def request(method, params=None, request_id=1):
    message = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return json.dumps(message)


class ServerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="tagging-server-")
        cls.store = os.path.join(cls.dir, "profile.db")
        build.rebuild(os.path.join(DATA, "customers.csv"), os.path.join(DATA, "transactions.csv"), cls.store,
                      TAXONOMY)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def server(self, legacy=True, store=None):
        server = Server(Reader(store or self.store, TAXONOMY))
        if legacy:
            self.ask(server, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                            "clientInfo": {"name": "test", "version": "1"}})
        return server

    def ask(self, server, method, params=None, request_id=1):
        reply = server.handle_line(request(method, params, request_id))
        return json.loads(reply) if reply is not None else None

    def call(self, server, name, arguments):
        reply = self.ask(server, "tools/call", {"name": name, "arguments": arguments})
        self.assertIn("result", reply, reply)
        return reply["result"]

    def structured(self, server, name, arguments):
        result = self.call(server, name, arguments)
        self.assertFalse(result["isError"], result)
        self.assertEqual(json.loads(result["content"][0]["text"]), result["structuredContent"])
        return result["structuredContent"]


class LegacyLifecycle(ServerCase):
    def test_initialize_negotiates_a_supported_version(self):
        server = Server(Reader(self.store, TAXONOMY))
        reply = self.ask(server, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
        self.assertEqual(reply["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(reply["result"]["capabilities"], {"tools": {"listChanged": False}})
        self.assertEqual(reply["result"]["serverInfo"]["name"], "customer-tagging-profiles")
        other = Server(Reader(self.store, TAXONOMY))
        reply = self.ask(other, "initialize", {"protocolVersion": "2024-01-01", "capabilities": {}})
        self.assertEqual(reply["result"]["protocolVersion"], "2025-11-25")

    def test_initialized_notification_gets_no_reply(self):
        server = self.server()
        self.assertIsNone(server.handle_line(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})))

    def test_a_request_before_initialize_without_meta_is_refused(self):
        reply = self.ask(Server(Reader(self.store, TAXONOMY)), "tools/list")
        self.assertEqual(reply["error"]["code"], -32602)
        self.assertIn("initialize", reply["error"]["message"])

    def test_initialize_without_a_version_is_invalid(self):
        reply = self.ask(Server(Reader(self.store, TAXONOMY)), "initialize", {"capabilities": {}})
        self.assertEqual(reply["error"]["code"], -32602)

    def test_tools_list_is_complete_and_deterministic(self):
        server = self.server()
        first = self.ask(server, "tools/list")["result"]["tools"]
        self.assertEqual([t["name"] for t in first], ["list_tags", "get_customer_tags", "explain_tag",
                                                      "find_customers_by_tag", "tag_summary", "customer_tag_history"])
        self.assertEqual(first, self.ask(server, "tools/list", request_id=2)["result"]["tools"])
        for tool in first:
            self.assertEqual(tool["annotations"]["readOnlyHint"], True)
            self.assertNotIn("resultType", self.ask(server, "tools/list")["result"])


class ModernRequests(ServerCase):
    def test_discover(self):
        reply = self.ask(self.server(legacy=False), "server/discover", {"_meta": MODERN_META})
        result = reply["result"]
        self.assertEqual(result["resultType"], "complete")
        self.assertIn("2026-07-28", result["supportedVersions"])
        self.assertEqual(result["capabilities"], {"tools": {"listChanged": False}})
        self.assertEqual(result["_meta"]["io.modelcontextprotocol/serverInfo"]["name"], "customer-tagging-profiles")

    def test_every_modern_request_stands_alone(self):
        server = self.server(legacy=False)
        reply = self.ask(server, "tools/call", {"_meta": MODERN_META, "name": "tag_summary", "arguments": {}})
        self.assertEqual(reply["result"]["resultType"], "complete")
        self.assertFalse(reply["result"]["isError"])

    def test_an_unsupported_version_lists_the_supported_ones(self):
        meta = dict(MODERN_META, **{"io.modelcontextprotocol/protocolVersion": "1900-01-01"})
        reply = self.ask(self.server(legacy=False), "tools/list", {"_meta": meta})
        self.assertEqual(reply["error"]["code"], -32022)
        self.assertEqual(reply["error"]["data"]["requested"], "1900-01-01")
        self.assertIn("2026-07-28", reply["error"]["data"]["supported"])

    def test_missing_client_capabilities_is_invalid(self):
        reply = self.ask(self.server(legacy=False), "tools/list",
                         {"_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}})
        self.assertEqual(reply["error"]["code"], -32602)


class JsonRpcErrors(ServerCase):
    def test_error_codes(self):
        server = self.server()
        cases = [
            ("{not json", -32700),
            (json.dumps([{"jsonrpc": "2.0", "id": 1, "method": "ping"}]), -32600),
            (json.dumps({"id": 1, "method": "ping"}), -32600),
            (json.dumps({"jsonrpc": "2.0", "id": True, "method": "ping"}), -32600),
            (json.dumps({"jsonrpc": "2.0", "id": 1, "method": "resources/list"}), -32601),
            (json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "drop_table"}}), -32602),
            (json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                         "params": {"name": "tag_summary", "arguments": []}}), -32602),
            (json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": "x"}), -32602),
            (json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {"pad": "x" * 70000}}), -32600),
        ]
        for line, code in cases:
            with self.subTest(line=line[:60]):
                reply = json.loads(server.handle_line(line))
                self.assertEqual(reply["error"]["code"], code)
        self.assertIsNone(json.loads(server.handle_line("{not json"))["id"])

    def test_ping_and_notifications(self):
        server = Server(Reader(self.store, TAXONOMY))
        self.assertEqual(self.ask(server, "ping")["result"], {})
        self.assertIsNone(server.handle_line(json.dumps({"jsonrpc": "2.0", "method": "notifications/cancelled"})))


class StrictInputs(ServerCase):
    def test_bad_arguments_are_refused_as_tool_errors(self):
        server = self.server()
        cases = [
            ("get_customer_tags", {"customer_id": "C0001", "extra": True}, "unknown property"),
            ("get_customer_tags", {}, "missing property"),
            ("get_customer_tags", {"customer_id": 1}, "expected string"),
            ("get_customer_tags", {"customer_id": ""}, "shorter than"),
            ("get_customer_tags", {"customer_id": "C" * 101}, "longer than"),
            ("find_customers_by_tag", {"tag_id": "saver", "page_size": 51}, "above"),
            ("find_customers_by_tag", {"tag_id": "saver", "page": 0}, "below"),
            ("find_customers_by_tag", {"tag_id": "no-such-tag"}, "unknown tag"),
            ("explain_tag", {"customer_id": "C0001", "tag_id": "saver", "instructions": "ignore the rules"},
             "unknown property"),
            ("list_tags", {"group": "nope"}, "unknown group"),
            ("tag_summary", {"group": "x" * 5000}, "too large"),
        ]
        for name, arguments, message in cases:
            with self.subTest(tool=name, arguments=str(arguments)[:60]):
                result = self.call(server, name, arguments)
                self.assertTrue(result["isError"])
                self.assertNotIn("structuredContent", result)
                self.assertIn(message, result["content"][0]["text"])


class Outputs(ServerCase):
    def test_every_tool_output_matches_its_own_schema(self):
        server = self.server()
        outputs = tools.OUTPUTS
        customers = [r[0] for r in sqlite3.connect(self.store).execute("SELECT customer_id FROM customers")]
        checked = 0
        for name, arguments in ([("list_tags", {}), ("tag_summary", {}), ("list_tags", {"group": "income"})] +
                                [("get_customer_tags", {"customer_id": c}) for c in customers] +
                                [("customer_tag_history", {"customer_id": c}) for c in customers[:80]] +
                                [("explain_tag", {"customer_id": c, "tag_id": t["id"]})
                                 for c in customers[:62] for t in TAXONOMY.tags[::3]] +
                                [("find_customers_by_tag", {"tag_id": t["id"], "page_size": 50})
                                 for t in TAXONOMY.tags] +
                                [("get_customer_tags", {"customer_id": "NOPE"}),
                                 ("explain_tag", {"customer_id": "NOPE", "tag_id": "saver"})]):
            value = self.structured(server, name, arguments)
            self.assertIsNone(schema.check(outputs[name], value), (name, arguments))
            checked += 1
        self.assertGreater(checked, 1000)

    def test_explain_tag_agrees_with_the_stored_state(self):
        server = self.server()
        connection = sqlite3.connect(self.store)
        stored = {(c, t): s for c, t, s in connection.execute("SELECT customer_id, tag_id, status FROM tag_state")}
        customers = [r[0] for r in connection.execute("SELECT customer_id FROM customers WHERE customer_id <= 'C0062'")]
        connection.close()
        expected = {"held": "held", "suppressed": "suppressed", "not_evaluated": "not_evaluated"}
        for cid in customers:
            for tag in TAXONOMY.tags:
                value = self.structured(server, "explain_tag", {"customer_id": cid, "tag_id": tag["id"]})
                self.assertEqual(value["status"], expected.get(stored.get((cid, tag["id"])), "not_held"),
                                 (cid, tag["id"]))
                if value["status"] == "not_held":
                    self.assertTrue(value["unmet"] or value["suppressed_by"], (cid, tag["id"]))

    def test_why_not_lists_the_unmet_conditions(self):
        value = self.structured(self.server(), "explain_tag", {"customer_id": "C0002", "tag_id": "salary-earner"})
        self.assertEqual(value["status"], "not_held")
        self.assertEqual(value["unmet"], ["salary_months"])
        self.assertEqual(value["evidence"][0]["display"], "5")
        self.assertEqual(value["evidence"][0]["threshold_display"], "6")

    def test_paging_covers_every_holder_once(self):
        server = self.server()
        summary = {t["id"]: t["held"] for t in self.structured(server, "tag_summary", {})["tags"]}
        seen, page = [], 1
        while page:
            value = self.structured(server, "find_customers_by_tag", {"tag_id": "active-customer", "page": page,
                                                                      "page_size": 7})
            seen.extend(c["customer_id"] for c in value["customers"])
            page = value["next_page"]
        self.assertEqual(len(seen), summary["active-customer"])
        self.assertEqual(len(seen), len(set(seen)))

    def test_results_carry_the_prohibited_uses_and_no_names(self):
        server = self.server()
        value = self.structured(server, "find_customers_by_tag", {"tag_id": "saver"})
        self.assertEqual(value["prohibited_uses"], TAXONOMY.governance["prohibited_uses"])
        for entry in value["customers"]:
            self.assertEqual(entry["display_name"], "Customer " + entry["customer_id"])
        self.assertNotIn("Synthetic Customer", json.dumps(value))


class ReadOnlyAndLimits(ServerCase):
    def test_the_readers_connection_cannot_write(self):
        reader = Reader(self.store, TAXONOMY)
        connection = reader.connect()
        try:
            for statement in ("DELETE FROM tag_state", "UPDATE meta SET value = 'x'", "CREATE TABLE x (y)",
                              "INSERT INTO meta VALUES ('a', 'b')"):
                with self.assertRaises(sqlite3.OperationalError):
                    connection.execute(statement)
        finally:
            connection.close()

    def test_the_server_code_has_no_network_processes_or_writes(self):
        forbidden = {"socket", "ssl", "http", "urllib", "requests", "ftplib", "smtplib", "subprocess",
                     "multiprocessing", "threading", "shutil"}
        write_sql = re.compile(r"\b(INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|REPLACE|ATTACH|PRAGMA\s+\w+\s*=)\b")
        folder = os.path.join(ROOT, "server")
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".py"):
                continue
            with open(os.path.join(folder, name), encoding="utf-8") as handle:
                source = handle.read()
            for node in ast.walk(ast.parse(source)):
                modules = []
                if isinstance(node, ast.Import):
                    modules = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    modules = [(node.module or "").split(".")[0]]
                for module in modules:
                    self.assertNotIn(module, forbidden, "{} imports {}".format(name, module))
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    self.assertIsNone(write_sql.search(node.value), "{} has write SQL: {}".format(name, node.value))

    def test_a_missing_or_stale_store_is_a_tool_error(self):
        server = self.server(store=os.path.join(self.dir, "missing.db"))
        result = self.call(server, "tag_summary", {})
        self.assertTrue(result["isError"])
        self.assertIn("not available", result["content"][0]["text"])

    def test_a_query_over_budget_is_stopped(self):
        saved = tools.SQL_STEP_BUDGET
        tools.SQL_STEP_BUDGET = 1000
        try:
            result = self.call(self.server(), "tag_summary", {})
        finally:
            tools.SQL_STEP_BUDGET = saved
        self.assertTrue(result["isError"])
        self.assertIn("took too long", result["content"][0]["text"])

    @unittest.skipUnless(hasattr(__import__("signal"), "SIGALRM"), "needs SIGALRM")
    def test_a_slow_call_times_out(self):
        import time

        class Slow(Reader):
            def call(self, name, arguments):
                time.sleep(3)

        server = Server(Slow(self.store, TAXONOMY), timeout_seconds=0.2)
        self.ask(server, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {}})
        result = self.call(server, "tag_summary", {})
        self.assertTrue(result["isError"])
        self.assertIn("took too long", result["content"][0]["text"])

    def test_an_output_that_breaks_its_schema_is_never_returned(self):
        class Broken(Reader):
            def call(self, name, arguments):
                return {"customers": "not a number"}

        server = Server(Broken(self.store, TAXONOMY))
        self.ask(server, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {}})
        reply = self.ask(server, "tools/call", {"name": "tag_summary", "arguments": {}})
        self.assertEqual(reply["error"]["code"], -32603)
        self.assertNotIn("not a number", json.dumps(reply))


class Stdio(ServerCase):
    def test_a_session_over_stdio(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        lines = [request("initialize", {"protocolVersion": "2025-11-25", "capabilities": {}}),
                 json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                 request("tools/list", request_id=2),
                 request("tools/call", {"name": "get_customer_tags", "arguments": {"customer_id": "C0011"}}, 3)]
        result = subprocess.run([sys.executable, os.path.join(ROOT, "bin", "profile-reader"), "--store", self.store],
                                input="\n".join(lines) + "\n", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                universal_newlines=True, env=env, cwd=self.dir, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        replies = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([r["id"] for r in replies], [1, 2, 3])
        tags = [t["id"] for t in replies[2]["result"]["structuredContent"]["tags"]]
        self.assertIn("recurring-bills", tags)


class Packaging(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "cognic.plugin.json"), encoding="utf-8") as handle:
            cls.safety = json.load(handle)
        with open(os.path.join(ROOT, ".mcp.json"), encoding="utf-8") as handle:
            cls.mcp = json.load(handle)

    def test_schemas_stay_inside_the_safety_file_vocabulary(self):
        for tool in tools.tool_list():
            for key in ("inputSchema", "outputSchema"):
                with self.subTest(tool=tool["name"], schema=key):
                    self.assertLessEqual(schema.check_schema(tool[key]), schema.MAX_NODES)

    def test_tool_list_digest_is_recomputed(self):
        self.assertEqual(self.safety["servers"][0]["toolListDigest"], tools.tool_list_digest())

    def test_safety_file_tools_equal_the_servers_tools(self):
        declared = {t["name"]: t for t in self.safety["tools"]}
        self.assertEqual(sorted(declared), sorted(t["name"] for t in tools.tool_list()))
        for tool in tools.tool_list():
            entry = declared[tool["name"]]
            for key in ("description", "inputSchema", "outputSchema"):
                self.assertEqual(entry[key], json.loads(json.dumps(tool[key])), (tool["name"], key))
            self.assertEqual((entry["effect"], entry["tier"], entry["consentClass"], entry["enforcement"]),
                             ("read", "reader", "none", "read-only"))
            self.assertEqual(entry["dataClasses"], ["confidential", "sensitive"])
            self.assertEqual(entry["credentials"], [])
            self.assertEqual(entry["scope"]["roles"], ["employee"])

    def test_one_stdio_server_with_no_network_and_no_credentials(self):
        servers = self.mcp["mcpServers"]
        self.assertEqual(list(servers), ["profiles"])
        declared = self.safety["servers"]
        self.assertEqual(len(declared), 1)
        self.assertEqual((declared[0]["id"], declared[0]["transport"]), ("profiles", "stdio"))
        self.assertEqual((servers["profiles"]["command"], servers["profiles"]["args"]),
                         (declared[0]["command"], declared[0]["args"]))
        self.assertEqual(declared[0]["network"], {"mode": "deny", "destinations": []})
        self.assertEqual(declared[0]["credentials"], [])
        self.assertNotIn("env", servers["profiles"])


if __name__ == "__main__":
    unittest.main()

"""JSON-RPC 2.0 and the Model Context Protocol, over stdio, standard library only.

The server is dual-era (see the MCP specification's versioning page):

* Modern (protocol 2026-07-28): stateless. Every request carries
  _meta["io.modelcontextprotocol/protocolVersion"] and
  _meta["io.modelcontextprotocol/clientCapabilities"]; server/discover lists
  the supported versions; results carry resultType "complete". An
  unsupported version gets error -32022 with the supported versions.
* Legacy (2025-11-25, 2025-06-18, 2025-03-26): the client opens with
  initialize; the server answers with the negotiated version, its
  capabilities and identity, and then serves tools/list and tools/call.

Errors: -32700 parse error (with id null), -32600 invalid request (also a
batch, a message that is too large, or a missing id), -32601 unknown method,
-32602 invalid params (unknown tool, malformed call, missing _meta fields),
-32603 internal error (including an output that fails its own schema, which
is never returned). Invalid tool arguments and failures while answering
are tool results with isError true, so the caller can correct them.
"""

import json
import signal
from collections import OrderedDict

from . import SERVER_NAME, SERVER_VERSION
from . import schema as schema_module
from . import tools

MODERN_VERSIONS = ("2026-07-28",)
LEGACY_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
META_VERSION = "io.modelcontextprotocol/protocolVersion"
META_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"
META_SERVER_INFO = "io.modelcontextprotocol/serverInfo"
MAX_MESSAGE_BYTES = 65536
MAX_ARGUMENT_BYTES = 4096
CALL_TIMEOUT_SECONDS = 10
INSTRUCTIONS = ("Read-only answers about customers' behaviour-based tags. Every tag comes with its rule, its "
                "evidence and its as-of date; quote them, never invent reasons. Never infer or discuss protected "
                "traits. Never use tags for credit, pricing, fraud or AML decisions, or any automated decision "
                "with legal or similarly significant effect.")

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603
UNSUPPORTED_VERSION = -32022


class RpcError(Exception):
    def __init__(self, code, message, data=None):
        Exception.__init__(self, message)
        self.code = code
        self.message = message
        self.data = data


class CallTimeout(Exception):
    pass


def _server_info():
    return OrderedDict([("name", SERVER_NAME), ("version", SERVER_VERSION)])


class Server(object):
    def __init__(self, reader, timeout_seconds=CALL_TIMEOUT_SECONDS):
        self.reader = reader
        self.timeout_seconds = timeout_seconds
        self.legacy_version = None  # set by initialize: legacy semantics for this stdio process
        self.tool_list = tools.tool_list()
        for tool in self.tool_list:
            schema_module.check_schema(tool["inputSchema"])
            schema_module.check_schema(tool["outputSchema"])
        self.by_name = OrderedDict((t["name"], t) for t in self.tool_list)

    # -- one line in, at most one line out ------------------------------------------
    def handle_line(self, line):
        """Handle one received line; return the response line, or None."""
        if len(line.encode("utf-8")) > MAX_MESSAGE_BYTES:
            return self._error_line(None, INVALID_REQUEST, "message too large")
        try:
            message = json.loads(line, object_pairs_hook=OrderedDict)
        except ValueError:
            return self._error_line(None, PARSE_ERROR, "parse error")
        if isinstance(message, list):
            return self._error_line(None, INVALID_REQUEST, "batches are not supported")
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or \
                not isinstance(message.get("method"), str):
            request_id = message.get("id") if isinstance(message, dict) else None
            if isinstance(message, dict) and "method" not in message and ("result" in message or "error" in message):
                return None  # a response sent to us: nothing to answer
            return self._error_line(request_id if _valid_id(request_id) else None, INVALID_REQUEST,
                                    "invalid request")
        is_notification = "id" not in message
        request_id = message.get("id")
        if not is_notification and not _valid_id(request_id):
            return self._error_line(None, INVALID_REQUEST, "the id must be a string or an integer")
        params = message.get("params", {})
        if not isinstance(params, dict):
            return None if is_notification else self._error_line(request_id, INVALID_PARAMS,
                                                                  "params must be an object")
        try:
            result = self.dispatch(message["method"], params, is_notification)
        except RpcError as exc:
            return None if is_notification else self._error_line(request_id, exc.code, exc.message, exc.data)
        except Exception:  # never let an internal failure leak details or kill the server
            return None if is_notification else self._error_line(request_id, INTERNAL_ERROR, "internal error")
        if is_notification:
            return None
        return json.dumps(OrderedDict([("jsonrpc", "2.0"), ("id", request_id), ("result", result)]),
                          ensure_ascii=False, separators=(",", ":"))

    def _error_line(self, request_id, code, message, data=None):
        error = OrderedDict([("code", code), ("message", message)])
        if data is not None:
            error["data"] = data
        return json.dumps(OrderedDict([("jsonrpc", "2.0"), ("id", request_id), ("error", error)]),
                          ensure_ascii=False, separators=(",", ":"))

    # -- methods -----------------------------------------------------------------------
    def dispatch(self, method, params, is_notification=False):
        meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
        modern = META_VERSION in meta
        if method == "initialize":
            return self._initialize(params)
        if method.startswith("notifications/"):
            return None  # initialized, cancelled, ...: nothing to do for a synchronous read-only server
        if modern:
            version = meta.get(META_VERSION)
            if version not in MODERN_VERSIONS:
                raise RpcError(UNSUPPORTED_VERSION, "Unsupported protocol version",
                               OrderedDict([("supported", list(MODERN_VERSIONS + LEGACY_VERSIONS)),
                                            ("requested", version)]))
            if not isinstance(meta.get(META_CAPABILITIES), dict):
                raise RpcError(INVALID_PARAMS, "missing _meta {}".format(META_CAPABILITIES))
        elif self.legacy_version is None and method != "ping":
            raise RpcError(INVALID_PARAMS, "missing _meta {}: send it on every request (protocol {}), or open "
                                           "with initialize (protocol {})".format(
                                               META_VERSION, MODERN_VERSIONS[0], ", ".join(LEGACY_VERSIONS)))
        if method == "ping":
            result = OrderedDict()
        elif method == "server/discover":
            if not modern:
                raise RpcError(METHOD_NOT_FOUND, "server/discover is part of protocol {}".format(MODERN_VERSIONS[0]))
            result = OrderedDict([("supportedVersions", list(MODERN_VERSIONS + LEGACY_VERSIONS)),
                                  ("capabilities", OrderedDict([("tools", OrderedDict([("listChanged", False)]))])),
                                  ("instructions", INSTRUCTIONS)])
        elif method == "tools/list":
            result = OrderedDict([("tools", self.tool_list)])
        elif method == "tools/call":
            result = self._call(params)
        else:
            raise RpcError(METHOD_NOT_FOUND, "method not found: {}".format(method))
        if modern:
            result["resultType"] = "complete"
            result["_meta"] = OrderedDict([(META_SERVER_INFO, _server_info())])
        return result

    def _initialize(self, params):
        requested = params.get("protocolVersion")
        if not isinstance(requested, str):
            raise RpcError(INVALID_PARAMS, "initialize needs protocolVersion; this server supports {} and, "
                                           "without initialize, {}".format(", ".join(LEGACY_VERSIONS),
                                                                           MODERN_VERSIONS[0]))
        version = requested if requested in LEGACY_VERSIONS else LEGACY_VERSIONS[0]
        self.legacy_version = version
        return OrderedDict([("protocolVersion", version),
                            ("capabilities", OrderedDict([("tools", OrderedDict([("listChanged", False)]))])),
                            ("serverInfo", _server_info()), ("instructions", INSTRUCTIONS)])

    def _call(self, params):
        name = params.get("name")
        if not isinstance(name, str) or name not in self.by_name:
            raise RpcError(INVALID_PARAMS, "Unknown tool: {}".format(name if isinstance(name, str) else "(none)"))
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            raise RpcError(INVALID_PARAMS, "arguments must be an object")
        tool = self.by_name[name]
        if len(json.dumps(arguments)) > MAX_ARGUMENT_BYTES:
            return _tool_error("arguments are too large")
        problem = schema_module.check(tool["inputSchema"], arguments, "arguments")
        if problem:
            return _tool_error("invalid arguments: {}".format(problem))
        try:
            with _time_limit(self.timeout_seconds):
                structured = self.reader.call(name, arguments)
        except tools.ToolError as exc:
            return _tool_error(str(exc))
        except CallTimeout:
            return _tool_error("the request took too long and was stopped")
        problem = schema_module.check(tool["outputSchema"], structured, "result")
        if problem:
            raise RpcError(INTERNAL_ERROR, "the result did not match the tool's output schema")
        return OrderedDict([
            ("content", [OrderedDict([("type", "text"),
                                      ("text", json.dumps(structured, ensure_ascii=False, separators=(",", ":")))])]),
            ("structuredContent", structured),
            ("isError", False),
        ])


def _tool_error(message):
    return OrderedDict([("content", [OrderedDict([("type", "text"), ("text", message)])]), ("isError", True)])


def _valid_id(value):
    return isinstance(value, str) or (isinstance(value, int) and not isinstance(value, bool))


class _time_limit(object):
    """A wall-clock limit on one call where the platform has SIGALRM."""

    def __init__(self, seconds):
        self.seconds = seconds
        self.active = hasattr(signal, "SIGALRM") and seconds > 0

    def __enter__(self):
        if self.active:
            def expired(signum, frame):
                raise CallTimeout()
            self.previous = signal.signal(signal.SIGALRM, expired)
            signal.setitimer(signal.ITIMER_REAL, self.seconds)
        return self

    def __exit__(self, *exc):
        if self.active:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, self.previous)
        return False


def serve(server, stdin, stdout):
    """Read newline-delimited JSON-RPC from stdin until it closes."""
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        reply = server.handle_line(line)
        if reply is not None:
            stdout.write(reply + "\n")
            stdout.flush()

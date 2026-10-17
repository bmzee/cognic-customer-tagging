"""The reader: a read-only MCP tool server over stdio for the profile store.

python3 -m server --store profile.db

It opens the store read-only for every call, offers six tools with strict
input and output schemas (server/tools.py), and speaks JSON-RPC 2.0 and the
Model Context Protocol over stdio (server/protocol.py). It has no network
access, no credentials and no way to write.
"""

SERVER_NAME = "customer-tagging-profiles"
SERVER_VERSION = "0.3.0"

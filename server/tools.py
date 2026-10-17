"""The reader's tools: read-only queries of the profile store.

Every tool opens the store read-only (file:...?mode=ro, query_only), checks
it, answers from it and closes it again, so a rebuilt store is picked up on
the next call and nothing can be written. Inputs and outputs follow strict
schemas (server/schema.py); a result that does not match its own output
schema is never returned.
"""

import json
import os
from collections import OrderedDict

from engine import evaluate as evaluate_module
from engine import profile
from engine import store as store_module
from engine.data import parse_date
from engine.taxonomy import METRICS

from . import schema as s

MAX_PAGE_SIZE = 50
SQL_STEP_BUDGET = 20000000  # SQLite virtual-machine steps per call: a deterministic time limit


class ToolError(Exception):
    """A failure reported to the caller as a tool result with isError."""


# -- schemas ------------------------------------------------------------------------

ID = s.string(100, "a customer id", min_length=1)
TAG_ID = s.string(64, "a tag id from list_tags", min_length=1)
DATE = s.string(10, "YYYY-MM-DD, or empty")
USES = OrderedDict([
    ("intended_use", s.string(600, "what tags may be used for")),
    ("prohibited_uses", s.array(s.string(200), 10, "what tags must never be used for")),
])
EVIDENCE = s.obj(OrderedDict([
    ("id", s.string(64)),
    ("description", s.string(300)),
    ("metric", s.string(32, enum=METRICS)),
    ("window", s.string(60, "the dates the value covers")),
    ("value", s.number("the value the rule compared")),
    ("display", s.string(160, "the value as shown to staff")),
    ("available", s.boolean("false when the value could not be computed")),
    ("op", s.string(2, enum=["", ">=", ">", "<=", "<", "=="])),
    ("threshold", s.number()),
    ("threshold_display", s.string(160)),
    ("result", s.string(10, enum=["met", "not met", "unknown", "fact"])),
    ("numerator_display", s.string(160)),
    ("denominator_display", s.string(160)),
    ("numerator_window", s.string(60)),
    ("denominator_window", s.string(60)),
    ("months_met", s.array(s.string(7), 120, "YYYY-MM months that counted")),
    ("missing", s.array(s.string(64), 20, "input fields that were missing")),
    ("note", s.string(200)),
    ("details", s.array(s.string(300), 50)),
]), "one condition of the rule: what was measured, against what, and the result")
HELD_TAG = s.obj(OrderedDict([
    ("id", TAG_ID), ("name", s.string(120)), ("group", s.string(64)),
    ("reason", s.string(1000, "the reason in plain words, filled from the evidence")),
    ("rule", s.string(3000, "the rule in words")),
    ("entered_on", s.string(10, "first month-end check of the current run, or empty if new this month")),
    ("new_this_month", s.boolean()),
    ("since_window_start", s.boolean("held since the start of the kept history")),
    ("evidence", s.array(EVIDENCE, 20)),
    ("facts", s.array(EVIDENCE, 10, "extra evidence shown in the reason, never part of the decision")),
]))
DATA_NOTES = s.obj(OrderedDict([
    ("transactions_used", s.integer(0)),
    ("pending", s.integer(0, description="transactions dated after the as-of date")),
    ("rejected", s.array(s.obj(OrderedDict([("reason", s.string(64)), ("count", s.integer(0))])), 50)),
]))
NO_INPUT = s.obj(OrderedDict())
GROUP_INPUT = s.obj(OrderedDict([("group", s.string(64, "limit to one tag group", min_length=1))]),
                    optional=("group",))
CUSTOMER_INPUT = s.obj(OrderedDict([("customer_id", ID)]))


def _outputs():
    tag_entry = s.obj(OrderedDict([
        ("id", TAG_ID), ("name", s.string(120)), ("group", s.string(64)), ("description", s.string(400)),
        ("polarity", s.string(8, enum=["benefit", "burden", "neutral"])), ("rule", s.string(3000)),
        ("fields", s.array(s.string(64), 30)), ("limitations", s.array(s.string(300), 10)),
        ("exclusive_group", s.string(64, "empty when the tag is in no exclusive group")),
    ]))
    common = OrderedDict([("as_of", DATE), ("taxonomy_version", s.string(20))])
    return {
        "list_tags": s.obj(OrderedDict([("taxonomy_version", s.string(20)), ("taxonomy_hash", s.string(80)),
                                        ("tags", s.array(tag_entry, 60))] + list(USES.items()))),
        "get_customer_tags": s.obj(OrderedDict([
            ("customer_id", ID), ("found", s.boolean())] + list(common.items()) + [
            ("closed_on", DATE),
            ("tags", s.array(HELD_TAG, 60)),
            ("suppressed", s.array(s.obj(OrderedDict([("id", TAG_ID), ("name", s.string(120)),
                                                      ("suppressed_by", TAG_ID)])), 60)),
            ("not_evaluated", s.array(s.obj(OrderedDict([("id", TAG_ID), ("name", s.string(120)),
                                                         ("missing", s.array(s.string(64), 20))])), 60)),
            ("data_notes", DATA_NOTES)] + list(USES.items()))),
        "explain_tag": s.obj(OrderedDict([
            ("customer_id", ID), ("tag_id", TAG_ID), ("found", s.boolean())] + list(common.items()) + [
            ("status", s.string(16, enum=["held", "not_held", "suppressed", "not_evaluated", "closed",
                                          "unknown_customer"])),
            ("name", s.string(120)), ("description", s.string(400)), ("rule", s.string(3000)),
            ("reason", s.string(1000, "filled from the evidence; meaningful when the tag is held")),
            ("evidence", s.array(EVIDENCE, 20, "every condition, met or not")),
            ("facts", s.array(EVIDENCE, 10)),
            ("unmet", s.array(s.string(64), 20, "ids of the conditions that were not met")),
            ("missing", s.array(s.string(64), 20, "missing input fields, when not evaluated")),
            ("suppressed_by", s.string(64, "the higher-priority tag in the same group, or empty")),
            ("entered_on", DATE),
            ("limitations", s.array(s.string(300), 10))] + list(USES.items()))),
        "find_customers_by_tag": s.obj(OrderedDict([
            ("tag_id", TAG_ID)] + list(common.items()) + [
            ("total", s.integer(0)), ("page", s.integer(1)), ("page_size", s.integer(1, MAX_PAGE_SIZE)),
            ("customers", s.array(s.obj(OrderedDict([("customer_id", ID), ("display_name", s.string(120))])),
                                  MAX_PAGE_SIZE, "customer ids and display names only")),
            ("next_page", s.integer(0, description="0 when this is the last page"))] + list(USES.items()))),
        "tag_summary": s.obj(OrderedDict(list(common.items()) + [
            ("customers", s.integer(0, description="customers in the store, closed accounts included")),
            ("tags", s.array(s.obj(OrderedDict([
                ("id", TAG_ID), ("name", s.string(120)), ("group", s.string(64)),
                ("polarity", s.string(8, enum=["benefit", "burden", "neutral"])),
                ("held", s.integer(0)), ("suppressed", s.integer(0)), ("not_evaluated", s.integer(0)),
                ("prevalence", s.number("held divided by customers", 0, 1)),
            ])), 60))])),
        "customer_tag_history": s.obj(OrderedDict([
            ("customer_id", ID), ("found", s.boolean())] + list(common.items()) + [
            ("lifecycle_months", s.integer(0)),
            ("checkpoints", s.array(s.obj(OrderedDict([("checkpoint", DATE), ("tags", s.array(TAG_ID, 60))])), 24,
                                    "the tags held at each month-end check")),
            ("events", s.array(s.obj(OrderedDict([("checkpoint", DATE), ("tag_id", TAG_ID),
                                                  ("event", s.string(8, enum=["entered", "exited"])),
                                                  ("at_window_start", s.boolean())])), 500)),
        ])),
    }


OUTPUTS = _outputs()

PROHIBITED = ("Never use for credit, pricing, fraud or AML decisions, or any automated decision with legal or "
              "similarly significant effect.")
TOOLS = OrderedDict([
    ("list_tags", ("The tag taxonomy: every tag's rule in words, the data it reads, its limitations, and the "
                   "intended and prohibited uses. Read-only. " + PROHIBITED, GROUP_INPUT)),
    ("get_customer_tags", ("One customer's current tags, each with its reason, rule, every condition's evidence "
                           "and its as-of date, plus suppressed and not-evaluated tags and data notes. Read-only. "
                           + PROHIBITED, CUSTOMER_INPUT)),
    ("explain_tag", ("Why one tag does or does not apply to one customer: the rule in words and every "
                     "condition's value, threshold and result, including the unmet ones and any missing data. "
                     "Read-only. " + PROHIBITED,
                     s.obj(OrderedDict([("customer_id", ID), ("tag_id", TAG_ID)])))),
    ("find_customers_by_tag", ("Customers who hold a tag, one page at a time (at most {} per page): customer ids "
                               "and display names only. Use get_customer_tags or explain_tag to see why. Read-only. "
                               .format(MAX_PAGE_SIZE) + PROHIBITED,
                               s.obj(OrderedDict([("tag_id", TAG_ID),
                                                  ("page", s.integer(1, 100000, "1 for the first page")),
                                                  ("page_size", s.integer(1, MAX_PAGE_SIZE))]),
                                     optional=("page", "page_size")))),
    ("tag_summary", ("How many customers hold, are suppressed for, or cannot be evaluated for each tag, and the "
                     "share holding it. Aggregate counts only. Read-only.", GROUP_INPUT)),
    ("customer_tag_history", ("One customer's tags at each month-end check and when each tag entered or exited. "
                              "Read-only. " + PROHIBITED, CUSTOMER_INPUT)),
])
ANNOTATIONS = OrderedDict([("readOnlyHint", True), ("destructiveHint", False), ("idempotentHint", True),
                           ("openWorldHint", False)])
TITLES = {"list_tags": "List tags", "get_customer_tags": "Get a customer's tags", "explain_tag": "Explain a tag",
          "find_customers_by_tag": "Find customers by tag", "tag_summary": "Tag summary",
          "customer_tag_history": "A customer's tag history"}


def tool_list():
    """The canonical tool list, as tools/list returns it, in a fixed order."""
    return [OrderedDict([("name", name), ("title", TITLES[name]), ("description", description),
                         ("inputSchema", input_schema), ("outputSchema", OUTPUTS[name]),
                         ("annotations", ANNOTATIONS)])
            for name, (description, input_schema) in TOOLS.items()]


def tool_list_digest():
    """sha256 over the canonical JSON (sorted keys) of the tool list sorted by name."""
    import hashlib
    tools = sorted(tool_list(), key=lambda t: t["name"])
    payload = json.dumps(tools, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


# -- the store ------------------------------------------------------------------------

class Reader(object):
    """Answers tool calls from a profile store, read-only."""

    def __init__(self, store_path, taxonomy):
        self.store_path = store_path
        self.taxonomy = taxonomy
        self._checked = None  # (device, inode, size, mtime) of the last fully checked file

    def connect(self):
        try:
            info = os.stat(self.store_path)
        except OSError:
            raise ToolError("the profile store is not available")
        identity = (info.st_dev, info.st_ino, info.st_size, info.st_mtime)
        connection = store_module.connect_ro(self.store_path)
        try:
            if identity != self._checked:
                store_module.check_store(connection, self.taxonomy)
                self._checked = identity
            else:
                meta = store_module.meta(connection)
                if meta.get("state") != store_module.STATE_READY or meta.get("taxonomy_hash") != \
                        self.taxonomy.content_hash:
                    raise store_module.StoreError("the store is not ready for this taxonomy")
        except store_module.StoreError as exc:
            connection.close()
            raise ToolError("the profile store cannot be used: {}".format(exc))
        connection.set_progress_handler(_budget(), 1000)
        return connection

    def call(self, name, arguments):
        handler = getattr(self, "_" + name)
        connection = self.connect()
        try:
            return handler(connection, arguments)
        except store_module.sqlite3.OperationalError as exc:
            if "interrupted" in str(exc):
                raise ToolError("the request took too long and was stopped")
            raise
        finally:
            connection.close()

    # -- helpers -------------------------------------------------------------------
    def _uses(self):
        governance = self.taxonomy.governance
        return OrderedDict([("intended_use", governance["intended_use"]),
                            ("prohibited_uses", list(governance["prohibited_uses"]))])

    def _meta(self, connection):
        meta = store_module.meta(connection)
        return meta.get("as_of", ""), meta.get("taxonomy_version", self.taxonomy.version)

    def _tag(self, tag_id):
        tag = self.taxonomy.by_id.get(tag_id)
        if tag is None:
            raise ToolError("unknown tag id {!r}: use list_tags".format(tag_id))
        return tag

    def _customer_row(self, connection, customer_id):
        return connection.execute("SELECT notes, closed_on FROM customers WHERE customer_id = ?",
                                  (customer_id,)).fetchone()

    def _notes(self, text):
        notes = json.loads(text) if text else {}
        rejected = notes.get("rejected", {})
        return OrderedDict([
            ("transactions_used", int(notes.get("transactions_used", 0))),
            ("pending", int(notes.get("pending", 0))),
            ("rejected", [OrderedDict([("reason", reason), ("count", int(count))])
                          for reason, count in sorted(rejected.items())]),
        ])

    # -- tools ---------------------------------------------------------------------
    def _list_tags(self, connection, arguments):
        group = arguments.get("group")
        if group is not None and group not in self.taxonomy.groups:
            raise ToolError("unknown group {!r}".format(group))
        tags = []
        for tag in self.taxonomy.tags:
            if group is not None and tag["group"] != group:
                continue
            tags.append(OrderedDict([
                ("id", tag["id"]), ("name", tag["name"]), ("group", tag["group"]),
                ("description", tag["description"]), ("polarity", tag["polarity"]),
                ("rule", evaluate_module.rule_text(tag["rule"], self.taxonomy.base_currency)),
                ("fields", list(tag["fields"])), ("limitations", list(tag["limitations"])),
                ("exclusive_group", self.taxonomy.exclusive_of.get(tag["id"], "")),
            ]))
        result = OrderedDict([("taxonomy_version", self.taxonomy.version),
                              ("taxonomy_hash", self.taxonomy.content_hash), ("tags", tags)])
        result.update(self._uses())
        return result

    def _get_customer_tags(self, connection, arguments):
        customer_id = arguments["customer_id"]
        as_of, version = self._meta(connection)
        row = self._customer_row(connection, customer_id)
        result = OrderedDict([("customer_id", customer_id), ("found", row is not None), ("as_of", as_of),
                              ("taxonomy_version", version), ("closed_on", (row[1] or "") if row else ""),
                              ("tags", []), ("suppressed", []), ("not_evaluated", []),
                              ("data_notes", self._notes(row[0] if row else ""))])
        if row is not None:
            for tag_id, status, entered, new, since, suppressed_by, reason, rule, evidence, facts, missing in \
                    connection.execute(
                        "SELECT tag_id, status, entered_on, new_this_month, since_window_start, suppressed_by, "
                        "reason, rule, evidence, facts, missing FROM tag_state WHERE customer_id = ?",
                        (customer_id,)):
                tag = self.taxonomy.by_id.get(tag_id)
                if tag is None:
                    continue
                if status == "held":
                    result["tags"].append(OrderedDict([
                        ("id", tag_id), ("name", tag["name"]), ("group", tag["group"]), ("reason", reason or ""),
                        ("rule", rule or ""), ("entered_on", entered or ""), ("new_this_month", bool(new)),
                        ("since_window_start", bool(since)), ("evidence", json.loads(evidence or "[]")),
                        ("facts", json.loads(facts or "[]")),
                    ]))
                elif status == "suppressed":
                    result["suppressed"].append(OrderedDict([("id", tag_id), ("name", tag["name"]),
                                                             ("suppressed_by", suppressed_by or "")]))
                else:
                    result["not_evaluated"].append(OrderedDict([("id", tag_id), ("name", tag["name"]),
                                                                ("missing", json.loads(missing or "[]"))]))
            order = {t["id"]: i for i, t in enumerate(self.taxonomy.tags)}
            for key in ("tags", "suppressed", "not_evaluated"):
                result[key].sort(key=lambda item: order[item["id"]])
        result.update(self._uses())
        return result

    def _explain_tag(self, connection, arguments):
        customer_id, tag_id = arguments["customer_id"], arguments["tag_id"]
        tag = self._tag(tag_id)
        as_of_text, version = self._meta(connection)
        result = OrderedDict([("customer_id", customer_id), ("tag_id", tag_id), ("found", False),
                              ("as_of", as_of_text), ("taxonomy_version", version), ("status", "unknown_customer"),
                              ("name", tag["name"]), ("description", tag["description"]),
                              ("rule", evaluate_module.rule_text(tag["rule"], self.taxonomy.base_currency)),
                              ("reason", ""), ("evidence", []), ("facts", []), ("unmet", []), ("missing", []),
                              ("suppressed_by", ""), ("entered_on", ""), ("limitations", list(tag["limitations"]))])
        result.update(self._uses())
        row = self._customer_row(connection, customer_id)
        as_of = parse_date(as_of_text)
        if row is None or as_of is None:
            return result
        result["found"] = True
        versions = profile.load_versions(connection, customer_id, self.taxonomy.base_currency)
        closed_on = profile.load_closed_on(connection, customer_id)
        data = profile.customer_data(self.taxonomy, customer_id, versions, closed_on,
                                     profile.load_transactions(connection, customer_id),
                                     profile.load_buckets(connection, customer_id))
        if closed_on is not None and as_of >= closed_on:
            result["status"] = "closed"
            return result
        explained = evaluate_module.explain_one(self.taxonomy, data, as_of, tag_id)
        result["reason"] = explained.reason
        result["evidence"] = explained.evidence
        result["facts"] = explained.facts
        result["unmet"] = [item["id"] for item in explained.evidence if item["result"] == "not met"]
        result["missing"] = list(explained.missing) if explained.state is None else []
        result["suppressed_by"] = explained.suppressed_by or ""
        if explained.suppressed_by:
            result["status"] = "suppressed"
        elif explained.state is True:
            result["status"] = "held"
        elif explained.state is None:
            result["status"] = "not_evaluated"
        else:
            result["status"] = "not_held"
        entered = connection.execute("SELECT entered_on FROM tag_state WHERE customer_id = ? AND tag_id = ? AND "
                                     "status = 'held'", (customer_id, tag_id)).fetchone()
        result["entered_on"] = (entered[0] or "") if entered else ""
        return result

    def _find_customers_by_tag(self, connection, arguments):
        tag_id = arguments["tag_id"]
        self._tag(tag_id)
        page = arguments.get("page", 1)
        size = arguments.get("page_size", 20)
        as_of, version = self._meta(connection)
        total = connection.execute("SELECT COUNT(*) FROM tag_state WHERE tag_id = ? AND status = 'held'",
                                   (tag_id,)).fetchone()[0]
        rows = connection.execute(
            "SELECT customer_id FROM tag_state WHERE tag_id = ? AND status = 'held' ORDER BY customer_id "
            "LIMIT ? OFFSET ?", (tag_id, size, (page - 1) * size)).fetchall()
        result = OrderedDict([
            ("tag_id", tag_id), ("as_of", as_of), ("taxonomy_version", version), ("total", total), ("page", page),
            ("page_size", size),
            ("customers", [OrderedDict([("customer_id", cid), ("display_name", display_name(cid))])
                           for (cid,) in rows]),
            ("next_page", page + 1 if page * size < total else 0),
        ])
        result.update(self._uses())
        return result

    def _tag_summary(self, connection, arguments):
        group = arguments.get("group")
        if group is not None and group not in self.taxonomy.groups:
            raise ToolError("unknown group {!r}".format(group))
        as_of, version = self._meta(connection)
        customers = connection.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        counts = {}
        for tag_id, status, count in connection.execute(
                "SELECT tag_id, status, COUNT(*) FROM tag_state GROUP BY tag_id, status"):
            counts.setdefault(tag_id, {})[status] = count
        tags = []
        for tag in self.taxonomy.tags:
            if group is not None and tag["group"] != group:
                continue
            held = counts.get(tag["id"], {}).get("held", 0)
            tags.append(OrderedDict([
                ("id", tag["id"]), ("name", tag["name"]), ("group", tag["group"]), ("polarity", tag["polarity"]),
                ("held", held), ("suppressed", counts.get(tag["id"], {}).get("suppressed", 0)),
                ("not_evaluated", counts.get(tag["id"], {}).get("not_evaluated", 0)),
                ("prevalence", round(held / float(customers), 4) if customers else 0.0),
            ]))
        return OrderedDict([("as_of", as_of), ("taxonomy_version", version), ("customers", customers),
                            ("tags", tags)])

    def _customer_tag_history(self, connection, arguments):
        customer_id = arguments["customer_id"]
        as_of, version = self._meta(connection)
        found = self._customer_row(connection, customer_id) is not None
        checkpoints = [OrderedDict([("checkpoint", day), ("tags", json.loads(tags))]) for day, tags in
                       connection.execute("SELECT checkpoint, tags FROM checkpoint_tags WHERE customer_id = ? "
                                          "ORDER BY checkpoint", (customer_id,))]
        events = [OrderedDict([("checkpoint", day), ("tag_id", tag_id), ("event", event),
                               ("at_window_start", bool(start))]) for day, tag_id, event, start in
                  connection.execute("SELECT checkpoint, tag_id, event, at_window_start FROM tag_history "
                                     "WHERE customer_id = ? ORDER BY checkpoint, tag_id", (customer_id,))]
        return OrderedDict([("customer_id", customer_id), ("found", found), ("as_of", as_of),
                            ("taxonomy_version", version), ("lifecycle_months", self.taxonomy.lifecycle_months),
                            ("checkpoints", checkpoints), ("events", events)])


def display_name(customer_id):
    """A label for staff that identifies the record, never the person: the
    store holds no names (see docs/OPEN-QUESTIONS.md, Q28)."""
    return "Customer {}".format(customer_id)


def _budget():
    steps = [0]

    def handler():
        steps[0] += 1000
        return 1 if steps[0] > SQL_STEP_BUDGET else 0
    return handler

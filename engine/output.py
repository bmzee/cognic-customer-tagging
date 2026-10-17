"""Turn a Run into tagged.json, tagged.csv or a plain-text explanation."""

import csv
import io
import json
from collections import OrderedDict

from . import ENGINE_VERSION
from .evaluate import OP_WORDS

CSV_COLUMNS = ("as_of", "customer_id", "tag_id", "tag_name", "reason", "rule", "evidence")


def _tag_entry(result):
    entry = OrderedDict()
    entry["id"] = result.tag["id"]
    entry["name"] = result.tag["name"]
    entry["group"] = result.tag["group"]
    entry["reason"] = result.reason
    entry["rule"] = result.rule
    entry["evidence"] = result.evidence
    if result.facts:
        entry["facts"] = result.facts
    return entry


def customer_record(run, customer_id, include_unmet=False):
    results = run.results[customer_id]
    record = OrderedDict()
    record["customer_id"] = customer_id
    record["tags"] = [_tag_entry(r) for r in results.values() if r.state is True]
    record["not_evaluated"] = [
        OrderedDict([("id", r.tag["id"]), ("name", r.tag["name"]), ("missing", r.missing)])
        for r in results.values() if r.state is None
    ]
    if include_unmet:
        record["not_met"] = [_tag_entry(r) for r in results.values() if r.state is False]
    record["data_notes"] = run.per_customer_notes[customer_id]
    return record


def run_record(run, customer_ids=None, include_unmet=False):
    ids = list(run.results) if customer_ids is None else list(customer_ids)
    counts = OrderedDict((t["id"], 0) for t in run.taxonomy.tags)
    tagged = 0
    for cid in run.results:
        fired = run.tags_for(cid)
        tagged += 1 if fired else 0
        for tag_id in fired:
            counts[tag_id] += 1
    record = OrderedDict()
    record["engine_version"] = ENGINE_VERSION
    record["taxonomy_version"] = run.taxonomy.version
    record["as_of"] = run.as_of.isoformat()
    record["base_currency"] = run.taxonomy.base_currency
    record["summary"] = OrderedDict([
        ("customers", len(run.results)),
        ("customers_with_tags", tagged),
        ("tag_counts", counts),
    ])
    record["data_notes"] = OrderedDict([
        ("customers", run.customer_notes),
        ("transactions", run.run_notes),
    ])
    record["customers"] = [customer_record(run, cid, include_unmet) for cid in ids]
    return record


def to_json(record):
    return json.dumps(record, indent=2, ensure_ascii=False) + "\n"


def needs_text(item):
    """'at least 6', 'at most 25%', or for a tag condition just 'yes'/'no'."""
    if item["op"] == "==" and isinstance(item["threshold"], bool):
        return item["threshold_display"]
    return "{} {}".format(OP_WORDS[item["op"]], item["threshold_display"])


def _evidence_text(evidence):
    parts = []
    for item in evidence:
        parts.append("{}: {} (needs {}; {})".format(
            item["description"], item["display"], needs_text(item), item["result"]))
    return "; ".join(parts)


def csv_rows(run, customer_ids=None):
    rows = []
    as_of = run.as_of.isoformat()
    for cid in (list(run.results) if customer_ids is None else list(customer_ids)):
        results = run.results[cid]
        fired = [r for r in results.values() if r.state is True]
        if not fired:
            rows.append(OrderedDict([("as_of", as_of), ("customer_id", cid), ("tag_id", ""), ("tag_name", ""),
                                     ("reason", "no tag matched"), ("rule", ""), ("evidence", "")]))
        for r in fired:
            rows.append(OrderedDict([
                ("as_of", as_of), ("customer_id", cid), ("tag_id", r.tag["id"]),
                ("tag_name", r.tag["name"]), ("reason", r.reason), ("rule", r.rule),
                ("evidence", _evidence_text(r.evidence)),
            ]))
    return rows


def to_csv(run, customer_ids=None):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in csv_rows(run, customer_ids):
        writer.writerow(row)
    return buffer.getvalue()


def _evidence_lines(items, indent):
    lines = []
    for item in items:
        if "result" in item:
            line = "{}- {}: {} (needs {}) - {}".format(
                indent, item["description"], item["display"], needs_text(item), item["result"])
        else:
            line = "{}- {}: {}".format(indent, item["description"], item["display"])
        extra = []
        if "window" in item and "numerator_window" not in item:
            extra.append(item["window"])
        if "numerator_display" in item:
            extra.append("{} of {}".format(item["numerator_display"], item["denominator_display"])
                         if "numerator_window" not in item else
                         "{} ({}) vs {} ({})".format(item["numerator_display"], item["numerator_window"],
                                                     item["denominator_display"], item["denominator_window"]))
        if item.get("months_met"):
            extra.append("months: " + ", ".join(item["months_met"]))
        if "median_month_display" in item:
            extra.append("usual month: " + item["median_month_display"])
        if "missing" in item:
            extra.append("missing: " + ", ".join(item["missing"]))
        if "note" in item:
            extra.append(item["note"])
        if extra:
            line += " [" + "; ".join(extra) + "]"
        lines.append(line)
    return lines


def _result_lines(result):
    lines = ["  * {}".format(result.tag["name"]),
             "    Why: {}".format(result.reason),
             "    Rule: {}".format(result.rule),
             "    Evidence:"]
    lines.extend(_evidence_lines(result.evidence, "      "))
    if result.facts:
        lines.append("    Also shown:")
        lines.extend(_evidence_lines(result.facts, "      "))
    return lines


def explain_text(run, customer_id, why=None):
    results = run.results[customer_id]
    lines = ["Customer {}, as of {}".format(customer_id, run.as_of.isoformat())]
    if why is not None:
        result = results[why]
        status = {True: "applies", False: "does not apply", None: "could not be evaluated"}[result.state]
        lines.append("Tag {} ({}) {}.".format(result.tag["name"], why, status))
        lines.extend(_result_lines(result))
        if result.state is None:
            lines.append("    Missing data: " + ", ".join(result.missing))
    else:
        fired = [r for r in results.values() if r.state is True]
        lines.append("Tags ({}):".format(len(fired)) if fired else "Tags: none matched.")
        for result in fired:
            lines.extend(_result_lines(result))
        unknown = [r for r in results.values() if r.state is None]
        if unknown:
            lines.append("Not evaluated (missing data):")
            for r in unknown:
                lines.append("  * {}: needs {}".format(r.tag["name"], ", ".join(r.missing)))
    notes = run.per_customer_notes[customer_id]
    skipped = ", ".join("{} {}".format(k, v) for k, v in notes["skipped"].items())
    line = "Data notes: {} transactions used".format(notes["transactions_used"])
    if skipped:
        line += "; skipped: " + skipped
    if notes["currency_defaulted"]:
        line += "; currency assumed to be the home currency for {}".format(notes["currency_defaulted"])
    lines.append(line)
    return "\n".join(lines) + "\n"


def list_tags_text(taxonomy):
    lines = ["Taxonomy {} ({} tags, base currency {})".format(
        taxonomy.version, len(taxonomy.tags), taxonomy.base_currency)]
    from .evaluate import rule_text
    for tag in taxonomy.tags:
        lines.append("")
        lines.append("{} ({}, {})".format(tag["name"], tag["id"], tag["group"]))
        lines.append("  {}".format(tag["description"]))
        lines.append("  Rule: {}".format(rule_text(tag["rule"], taxonomy.base_currency)))
        lines.append("  Reason shown: {}".format(tag["reason"]))
        lines.append("  Fields: {}".format(", ".join(tag["fields"])))
    return "\n".join(lines) + "\n"

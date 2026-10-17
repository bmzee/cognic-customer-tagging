"""Turn a Run into tagged.json, tagged.csv or a plain-text explanation."""

import csv
import io
import json
from collections import OrderedDict

from . import ENGINE_VERSION
from .evaluate import OP_WORDS

CSV_COLUMNS = ("as_of", "customer_id", "tag_id", "tag_name", "entered_on", "reason", "rule", "evidence")


def _lifecycle_fields(run, customer_id, tag_id):
    life = run.lifecycles.get(customer_id)
    if life is None or tag_id not in life.entered_on:
        return None
    return OrderedDict([
        ("entered_on", life.entered_on[tag_id].isoformat() if life.entered_on[tag_id] else ""),
        ("new_this_month", life.new_this_month[tag_id]),
        ("since_window_start", life.since_window_start[tag_id]),
    ])


def tag_entry(result, lifecycle_fields=None):
    entry = OrderedDict()
    entry["id"] = result.tag["id"]
    entry["name"] = result.tag["name"]
    entry["group"] = result.tag["group"]
    entry["reason"] = result.reason
    entry["rule"] = result.rule
    entry["evidence"] = result.evidence
    entry["facts"] = result.facts
    if lifecycle_fields is not None:
        entry.update(lifecycle_fields)
    return entry


def customer_record(run, customer_id, include_unmet=False):
    results = run.results[customer_id]
    record = OrderedDict()
    record["customer_id"] = customer_id
    record["as_of"] = run.as_of.isoformat()
    record["tags"] = [tag_entry(r, _lifecycle_fields(run, customer_id, r.tag["id"]))
                      for r in results.values() if r.state is True]
    record["suppressed"] = [
        OrderedDict([("id", r.tag["id"]), ("name", r.tag["name"]), ("suppressed_by", r.suppressed_by)])
        for r in results.values() if r.suppressed_by
    ]
    record["not_evaluated"] = [
        OrderedDict([("id", r.tag["id"]), ("name", r.tag["name"]), ("missing", r.missing)])
        for r in results.values() if r.state is None
    ]
    life = run.lifecycles.get(customer_id)
    if life is not None:
        record["ended_this_month"] = list(life.ended_this_month)
        record["last_checkpoint"] = life.last_checkpoint.isoformat() if life.last_checkpoint else ""
    if include_unmet:
        record["not_met"] = [tag_entry(r) for r in results.values() if r.state is False]
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
    record["taxonomy_hash"] = run.taxonomy.content_hash
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
    if item["metric"] == "tag":
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
                                     ("entered_on", ""), ("reason", "no tag matched"), ("rule", ""),
                                     ("evidence", "")]))
        for r in fired:
            life = _lifecycle_fields(run, cid, r.tag["id"])
            rows.append(OrderedDict([
                ("as_of", as_of), ("customer_id", cid), ("tag_id", r.tag["id"]),
                ("tag_name", r.tag["name"]), ("entered_on", life["entered_on"] if life else ""),
                ("reason", r.reason), ("rule", r.rule), ("evidence", _evidence_text(r.evidence)),
            ]))
    return rows


def to_csv(run, customer_ids=None):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in csv_rows(run, customer_ids):
        writer.writerow(row)
    return buffer.getvalue()


def evidence_lines(items, indent):
    lines = []
    for item in items:
        if item["result"] != "fact":
            line = "{}- {}: {} (needs {}) - {}".format(
                indent, item["description"], item["display"], needs_text(item), item["result"])
        else:
            line = "{}- {}: {}".format(indent, item["description"], item["display"])
        extra = []
        if item["window"] and not item["numerator_window"]:
            extra.append(item["window"])
        if item["numerator_display"]:
            if item["numerator_window"]:
                extra.append("{} ({}) vs {} ({})".format(item["numerator_display"], item["numerator_window"],
                                                         item["denominator_display"], item["denominator_window"]))
            else:
                extra.append("{} of {}".format(item["numerator_display"], item["denominator_display"]))
        if item["months_met"]:
            extra.append("months: " + ", ".join(item["months_met"]))
        extra.extend(item["details"])
        if item["missing"]:
            extra.append("missing: " + ", ".join(item["missing"]))
        if item["note"]:
            extra.append(item["note"])
        if extra:
            line += " [" + "; ".join(extra) + "]"
        lines.append(line)
    return lines


def _result_lines(result, life=None):
    lines = ["  * {}".format(result.tag["name"])]
    if life is not None:
        if life["new_this_month"]:
            lines.append("    Since: new this month (not yet held at a month-end check)")
        elif life["entered_on"]:
            lines.append("    Since: held at every month-end check since {}{}".format(
                life["entered_on"], " (the start of the kept history)" if life["since_window_start"] else ""))
    lines.extend(["    Why: {}".format(result.reason),
                  "    Rule: {}".format(result.rule),
                  "    Evidence:"])
    lines.extend(evidence_lines(result.evidence, "      "))
    if result.facts:
        lines.append("    Also shown:")
        lines.extend(evidence_lines(result.facts, "      "))
    if result.suppressed_by:
        lines.append("    Suppressed: {} takes priority in the same group".format(result.suppressed_by))
    return lines


def explain_text(run, customer_id, why=None):
    results = run.results[customer_id]
    lines = ["Customer {}, as of {}".format(customer_id, run.as_of.isoformat())]
    if why is not None:
        result = results[why]
        if result.suppressed_by:
            status = "does not apply: its rule is met, but {} takes priority".format(result.suppressed_by)
        else:
            status = {True: "applies", False: "does not apply", None: "could not be evaluated"}[result.state]
        lines.append("Tag {} ({}) {}.".format(result.tag["name"], why, status))
        lines.extend(_result_lines(result, _lifecycle_fields(run, customer_id, why)))
        if result.state is None:
            lines.append("    Missing data: " + ", ".join(result.missing))
    else:
        fired = [r for r in results.values() if r.state is True]
        lines.append("Tags ({}):".format(len(fired)) if fired else "Tags: none matched.")
        for result in fired:
            lines.extend(_result_lines(result, _lifecycle_fields(run, customer_id, result.tag["id"])))
        suppressed = [r for r in results.values() if r.suppressed_by]
        if suppressed:
            lines.append("Suppressed by a higher-priority tag in the same group:")
            for r in suppressed:
                lines.append("  * {}: {} takes priority".format(r.tag["name"], r.suppressed_by))
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
    lines = ["Taxonomy {} ({} tags, base currency {}, {})".format(
        taxonomy.version, len(taxonomy.tags), taxonomy.base_currency, taxonomy.content_hash)]
    from .evaluate import rule_text
    for tag in taxonomy.tags:
        lines.append("")
        lines.append("{} ({}, {})".format(tag["name"], tag["id"], tag["group"]))
        lines.append("  {}".format(tag["description"]))
        lines.append("  Rule: {}".format(rule_text(tag["rule"], taxonomy.base_currency)))
        lines.append("  Reason shown: {}".format(tag["reason"]))
        lines.append("  Fields: {}".format(", ".join(tag["fields"])))
        if tag["id"] in taxonomy.exclusive_of:
            lines.append("  Exclusive group: {}".format(taxonomy.exclusive_of[tag["id"]]))
    return "\n".join(lines) + "\n"

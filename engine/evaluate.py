"""Evaluate tags for customers and build the explanation for each one.

Logic is three-valued: a condition is met, not met, or unknown (an input
field it needs is missing). "all" is met when every child is met; "any" when
at least one is. A tag is given only when its rule is met. A tag whose rule
is unknown is reported as "not evaluated" together with the missing fields.

Every condition is evaluated (no short-circuit), so the evidence always
shows every number the rule looked at.

Evidence items have one fixed shape: every key is always present, with ""
or [] or 0 when it does not apply, so a strict output schema can describe
them (see EVIDENCE_KEYS).

Exclusive groups: when several tags of one group hold, the first in the
group's priority order is kept and the others are reported as suppressed.
"""

from collections import OrderedDict
from decimal import Decimal, ROUND_HALF_EVEN

from . import features
from . import taxonomy as taxonomy_module
from . import windows

QUANTUM = {
    "count": Decimal(1),
    "amount": Decimal("0.01"),
    "percent": Decimal("0.0001"),
    "times": Decimal("0.01"),
    "rate": Decimal("0.01"),
    "days": Decimal(1),
}

OP_WORDS = {">=": "at least", ">": "more than", "<=": "at most", "<": "less than", "==": "exactly"}

EVIDENCE_KEYS = (
    "id", "description", "metric", "window", "value", "display", "available", "op", "threshold",
    "threshold_display", "result", "numerator_display", "denominator_display", "numerator_window",
    "denominator_window", "months_met", "missing", "note", "details",
)


def leaf_format(leaf):
    return leaf.get("format") or taxonomy_module.DEFAULT_FORMAT[leaf["metric"]]


def quantize(value, fmt):
    """Round a value to the precision it is shown with, so the decision and
    the evidence always agree."""
    if value is None or isinstance(value, bool) or fmt == "yesno":
        return value
    return Decimal(value).quantize(QUANTUM[fmt], rounding=ROUND_HALF_EVEN)


def _plain(number):
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def display(value, fmt, currency):
    if value is None:
        return "not available"
    if fmt == "yesno":
        return "yes" if value else "no"
    q = quantize(value, fmt)
    if fmt == "count":
        return "{:,}".format(int(q))
    if fmt == "amount":
        return "{:,.2f} {}".format(q, currency)
    if fmt == "percent":
        return "{}%".format(_plain(q * 100))
    if fmt == "times":
        return "{} times".format(_plain(q))
    if fmt == "rate":
        return _plain(q)
    if fmt == "days":
        days = int(q)
        if abs(days) >= 365:
            years = (Decimal(days) / Decimal("365.25")).quantize(Decimal("0.1"), rounding=ROUND_HALF_EVEN)
            return "{:,} days ({} years)".format(days, years)
        return "{:,} days".format(days)
    raise ValueError(fmt)  # pragma: no cover


def json_number(value, fmt):
    """A JSON number for the evidence: 0 when unavailable, 1/0 for yes/no."""
    if value is None:
        return 0
    if isinstance(value, bool) or fmt == "yesno":
        return 1 if value else 0
    q = quantize(value, fmt)
    if fmt in ("count", "days"):
        return int(q)
    return float(q)


def _part_format(spec):
    return spec.get("format") or taxonomy_module.DEFAULT_FORMAT[spec["metric"]]


def _parts(leaf, measured, currency):
    """Displays for a share's or ratio's numerator and denominator."""
    if leaf["metric"] == "share":
        fmt = "count" if leaf["by"] == "count" else "amount"
        formats = (fmt, fmt)
    elif leaf["metric"] == "ratio":
        formats = (_part_format(leaf["numerator"]), _part_format(leaf["denominator"]))
    else:
        return None
    top = measured.details.get("numerator")
    bottom = measured.details.get("denominator")
    return display(top, formats[0], currency), display(bottom, formats[1], currency)


def leaf_text(leaf, currency):
    """Plain-words text of one condition, e.g.
    'months with a salary credit [each month: count >= 1], in the last 6
    complete months: at least 6'."""
    metric = leaf["metric"]
    text = leaf["description"]
    if metric == "months_where":
        monthly = leaf["monthly"]
        text += " [each month: {} {} {}]".format(monthly["measure"].replace("_", " "), monthly["op"], monthly["value"])
    if metric == "recurring":
        period = leaf["period_months"]
        floor = leaf.get("amount_floor")
        text += " [same payee {}, in at least {} months, still current, each month's average payment within {}% " \
                "of the usual amount{}{}]".format(
                    "every month" if period == 1 else "every {} months".format(period), leaf["min_occurrences"],
                    _plain(Decimal(str(leaf["amount_tolerance"])) * 100),
                    "" if not floor else " (or {})".format(display(Decimal(str(floor)), "amount", currency)),
                    "" if not leaf.get("max_missed") else ", at most {} missed".format(leaf["max_missed"]))
    if "window" in leaf:
        text += ", in {}".format(windows.describe(leaf["window"]))
    if metric == "ratio":
        text += " ({} vs {})".format(windows.describe(leaf["numerator"]["window"]),
                                     windows.describe(leaf["denominator"]["window"]))
    if "op" not in leaf:
        return text
    if metric == "tag":
        return "{}: {}".format(text, "yes" if leaf["value"] else "no")
    threshold = display(Decimal(str(leaf["value"])), leaf_format(leaf), currency)
    return "{}: {} {}".format(text, OP_WORDS[leaf["op"]], threshold)


def rule_text(node, currency, top=True):
    if "all" in node or "any" in node:
        children = node.get("all", node.get("any"))
        joiner = " AND " if "all" in node else " OR "
        parts = [rule_text(child, currency, top=False) for child in children]
        if len(parts) == 1:
            return parts[0]
        joined = joiner.join(parts)
        return joined if top else "(" + joined + ")"
    return leaf_text(node, currency)


def _evidence(leaf, measured, currency, is_fact):
    fmt = leaf_format(leaf)
    item = OrderedDict((key, None) for key in EVIDENCE_KEYS)
    item["id"] = leaf["id"]
    item["description"] = leaf["description"]
    item["metric"] = leaf["metric"]
    item["window"] = measured.window.label() if measured.window is not None else ""
    item["value"] = json_number(measured.value, fmt)
    item["display"] = display(measured.value, fmt, currency)
    item["available"] = measured.value is not None
    state = None
    if is_fact:
        item["op"] = ""
        item["threshold"] = 0
        item["threshold_display"] = ""
        item["result"] = "fact"
    else:
        threshold = leaf["value"]
        if leaf["metric"] == "tag":
            item["op"] = "=="
            item["threshold"] = 1 if threshold else 0
            item["threshold_display"] = "yes" if threshold else "no"
        else:
            item["op"] = leaf["op"]
            item["threshold"] = json_number(Decimal(str(threshold)), fmt)
            item["threshold_display"] = display(Decimal(str(threshold)), fmt, currency)
        if measured.missing:
            state = None
        elif measured.value is None:
            state = False
        elif leaf["metric"] == "tag":
            state = measured.value == threshold
        else:
            state = features.compare(quantize(measured.value, fmt), leaf["op"],
                                     quantize(Decimal(str(threshold)), fmt))
        item["result"] = {True: "met", False: "not met", None: "unknown"}[state]
    parts = _parts(leaf, measured, currency)
    item["numerator_display"], item["denominator_display"] = parts if parts else ("", "")
    item["numerator_window"] = measured.details.get("numerator_window", "")
    item["denominator_window"] = measured.details.get("denominator_window", "")
    item["months_met"] = list(measured.details.get("months_met", []))
    item["missing"] = list(measured.missing)
    item["note"] = measured.note or ""
    lines = list(measured.lines)
    if "median_month" in measured.details:
        lines.append("usual month: " + display(measured.details["median_month"], "amount", currency))
    item["details"] = lines
    return item, state


def _evaluate_node(node, ctx, currency, evidence, missing, with_evidence):
    if "all" in node or "any" in node:
        is_all = "all" in node
        children = node["all"] if is_all else node["any"]
        if not with_evidence:
            # State only: stop at the first child that decides the result. An
            # unknown result still visits every child, so its missing fields
            # are complete.
            unknown = False
            for child in children:
                state = _evaluate_node(child, ctx, currency, evidence, missing, False)
                if state is (not is_all):
                    return state
                if state is None:
                    unknown = True
            return None if unknown else is_all
        states = [_evaluate_node(child, ctx, currency, evidence, missing, with_evidence) for child in children]
        if is_all:
            if False in states:
                return False
            return None if None in states else True
        if True in states:
            return True
        return None if None in states else False
    measured = features.measure(ctx, node)
    if with_evidence:
        item, state = _evidence(node, measured, currency, is_fact=False)
        evidence.append(item)
    else:
        state = leaf_state(node, measured, ctx)
    if state is None:
        missing.update(measured.missing)
    return state


def leaf_state(leaf, measured, ctx=None):
    """met (True), not met (False) or unknown (None), exactly as _evidence decides it."""
    if measured.missing:
        return None
    if measured.value is None:
        return False
    if leaf["metric"] == "tag":
        return measured.value == leaf["value"]
    meta = ctx.taxonomy.leaf_thresholds.get((ctx.tag_id, leaf["id"])) if ctx is not None else None
    if meta is None:
        fmt = leaf_format(leaf)
        meta = (fmt, quantize(Decimal(str(leaf["value"])), fmt))
        if ctx is not None:
            ctx.taxonomy.leaf_thresholds[(ctx.tag_id, leaf["id"])] = meta
    fmt, threshold = meta
    return features.compare(quantize(measured.value, fmt), leaf["op"], threshold)


def render_reason(template, values):
    def replace(match):
        return values[match.group(1)]
    return taxonomy_module.PLACEHOLDER_RE.sub(replace, template)


def _reason_values(evidence, facts):
    values = {}
    for item in list(evidence) + list(facts):
        values[item["id"]] = item["display"]
        if item["threshold_display"]:
            values[item["id"] + ".threshold"] = item["threshold_display"]
        if item["numerator_display"]:
            values[item["id"] + ".numerator"] = item["numerator_display"]
            values[item["id"] + ".denominator"] = item["denominator_display"]
    return values


class TagResult(object):
    __slots__ = ("tag", "state", "rule_state", "evidence", "facts", "missing", "reason", "rule", "suppressed_by")

    def __init__(self, tag, state, evidence, facts, missing, reason, rule, rule_state=None, suppressed_by=None):
        self.tag = tag
        self.state = state
        self.rule_state = state if rule_state is None else rule_state
        self.evidence = evidence
        self.facts = facts
        self.missing = missing
        self.reason = reason
        self.rule = rule
        self.suppressed_by = suppressed_by


def _explain(taxonomy, ctx, tag_id):
    """The full TagResult for one tag: every condition's evidence, the facts,
    the reason and the rule in words."""
    currency = taxonomy.base_currency
    tag = taxonomy.by_id[tag_id]
    ctx.tag_id = tag_id
    evidence, missing = [], set()
    state = _evaluate_node(tag["rule"], ctx, currency, evidence, missing, True)
    facts = []
    for fact in tag.get("facts", []):
        item, _ = _evidence(fact, features.measure(ctx, fact), currency, is_fact=True)
        facts.append(item)
    reason = render_reason(tag["reason"], _reason_values(evidence, facts))
    text = taxonomy.rule_texts.get(tag_id)
    if text is None:
        text = taxonomy.rule_texts[tag_id] = rule_text(tag["rule"], currency)
    return TagResult(tag, state, evidence, facts, sorted(missing), reason, text)


def _rule_states(taxonomy, ctx, with_evidence):
    currency = taxonomy.base_currency
    results = {}
    for tag_id in taxonomy.order:
        if with_evidence is True:
            result = _explain(taxonomy, ctx, tag_id)
            state, missing = result.state, result.missing
        else:
            ctx.tag_id = tag_id
            found = set()
            state = _evaluate_node(taxonomy.by_id[tag_id]["rule"], ctx, currency, None, found, False)
            missing = sorted(found)
            result = TagResult(taxonomy.by_id[tag_id], state, None, None, missing, None, None)
        ctx.tag_states[tag_id] = state
        ctx.tag_missing[tag_id] = missing
        results[tag_id] = result
    return results


def _apply_exclusive_groups(taxonomy, results):
    for group in taxonomy.exclusive_groups:
        winner = None
        for tag_id in group["priority"]:
            result = results[tag_id]
            if result.rule_state is True:
                if winner is None:
                    winner = tag_id
                else:
                    result.state = False
                    result.suppressed_by = winner


def evaluate_data(taxonomy, data, as_of, with_evidence=True):
    """Return {tag_id: TagResult} for every tag, in taxonomy order, for one
    customer's CustomerData at as_of.

    with_evidence: True builds the evidence, reason and rule for every tag;
    "held" builds them only for tags that hold (the states are identical);
    False gives states and missing fields only."""
    ctx = features.Context(taxonomy, data, as_of)
    results = _rule_states(taxonomy, ctx, with_evidence)
    _apply_exclusive_groups(taxonomy, results)
    if with_evidence == "held":
        for tag_id, result in results.items():
            if result.state is True:
                full = _explain(taxonomy, ctx, tag_id)
                full.state, full.rule_state, full.suppressed_by = result.state, result.rule_state, result.suppressed_by
                results[tag_id] = full
    return OrderedDict((tag["id"], results[tag["id"]]) for tag in taxonomy.tags)


def evaluate_customer(taxonomy, customer, txns, as_of, with_evidence=True):
    """Convenience wrapper: evaluate one customer from a list of transactions."""
    from . import aggregate
    data = aggregate.CustomerData.from_rows(customer, [t for t in txns if t.posted_date <= as_of],
                                            taxonomy.specs)
    return evaluate_data(taxonomy, data, as_of, with_evidence)

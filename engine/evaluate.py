"""Evaluate tags for customers and build the explanation for each one.

Logic is three-valued: a condition is met, not met, or unknown (an input
field it needs is missing). "all" is met when every child is met; "any" when
at least one is. A tag is given only when its rule is met. A tag whose rule
is unknown is reported as "not evaluated" together with the missing fields.

Every condition is evaluated (no short-circuit), so the evidence always
shows every number the rule looked at.
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
    if value is None or isinstance(value, bool) or fmt == "yesno":
        return value
    q = quantize(value, fmt)
    if fmt in ("count", "days"):
        return int(q)
    return float(q)


def _part_format(spec):
    return spec.get("format") or taxonomy_module.DEFAULT_FORMAT[spec["metric"]]


def _parts(leaf, measured, currency):
    """Displays and JSON values for a share's or ratio's numerator/denominator."""
    if leaf["metric"] == "share":
        fmt = "count" if leaf["by"] == "count" else "amount"
        formats = (fmt, fmt)
    elif leaf["metric"] == "ratio":
        formats = (_part_format(leaf["numerator"]), _part_format(leaf["denominator"]))
    else:
        return None
    top = measured.details.get("numerator")
    bottom = measured.details.get("denominator")
    return OrderedDict([
        ("numerator", (json_number(top, formats[0]), display(top, formats[0], currency))),
        ("denominator", (json_number(bottom, formats[1]), display(bottom, formats[1], currency))),
    ])


def leaf_text(leaf, currency):
    """Plain-words text of one condition, e.g.
    'months with a salary credit [each month: count >= 1], in the last 6
    complete months: at least 6'."""
    metric = leaf["metric"]
    text = leaf["description"]
    if metric == "months_where":
        monthly = leaf["monthly"]
        text += " [each month: {} {} {}]".format(monthly["measure"].replace("_", " "), monthly["op"], monthly["value"])
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
    item = OrderedDict()
    item["id"] = leaf["id"]
    item["description"] = leaf["description"]
    if measured.window is not None:
        item["window"] = measured.window.label()
    item["value"] = json_number(measured.value, fmt)
    item["display"] = display(measured.value, fmt, currency)
    state = None
    if not is_fact:
        threshold = leaf["value"]
        if leaf["metric"] == "tag":
            item["op"] = "=="
            item["threshold"] = threshold
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
    if parts:
        for name, (value, shown) in parts.items():
            item[name] = value
            item[name + "_display"] = shown
        if leaf["metric"] == "ratio":
            item["numerator_window"] = measured.details["numerator_window"]
            item["denominator_window"] = measured.details["denominator_window"]
    if "months_met" in measured.details:
        item["months_met"] = list(measured.details["months_met"])
    if "median_month" in measured.details:
        item["median_month_display"] = display(measured.details["median_month"], "amount", currency)
    if "account_open_date" in measured.details:
        item["account_open_date"] = measured.details["account_open_date"]
    if measured.missing:
        item["missing"] = list(measured.missing)
    if measured.note:
        item["note"] = measured.note
    return item, state


def _evaluate_node(node, ctx, currency, evidence, missing):
    if "all" in node or "any" in node:
        states = [_evaluate_node(child, ctx, currency, evidence, missing)
                  for child in node.get("all", node.get("any"))]
        if "all" in node:
            if False in states:
                return False
            return None if None in states else True
        if True in states:
            return True
        return None if None in states else False
    measured = features.measure(ctx, node)
    item, state = _evidence(node, measured, currency, is_fact=False)
    evidence.append(item)
    if state is None:
        missing.update(measured.missing)
    return state


def render_reason(template, values):
    def replace(match):
        return values[match.group(1)]
    return taxonomy_module.PLACEHOLDER_RE.sub(replace, template)


def _reason_values(evidence, facts):
    values = {}
    for item in list(evidence) + list(facts):
        values[item["id"]] = item["display"]
        if "threshold_display" in item:
            values[item["id"] + ".threshold"] = item["threshold_display"]
        if "numerator_display" in item:
            values[item["id"] + ".numerator"] = item["numerator_display"]
            values[item["id"] + ".denominator"] = item["denominator_display"]
    return values


class TagResult(object):
    __slots__ = ("tag", "state", "evidence", "facts", "missing", "reason", "rule")

    def __init__(self, tag, state, evidence, facts, missing, reason, rule):
        self.tag = tag
        self.state = state
        self.evidence = evidence
        self.facts = facts
        self.missing = missing
        self.reason = reason
        self.rule = rule


def evaluate_customer(taxonomy, customer, txns, as_of):
    """Return {tag_id: TagResult} for every tag, in taxonomy order."""
    currency = taxonomy.base_currency
    states, missing_by_tag, results = {}, {}, {}
    ctx = features.Context(customer, txns, as_of, states, missing_by_tag)
    for tag_id in taxonomy.order:
        tag = taxonomy.by_id[tag_id]
        evidence, missing = [], set()
        state = _evaluate_node(tag["rule"], ctx, currency, evidence, missing)
        facts = []
        for fact in tag.get("facts", []):
            item, _ = _evidence(fact, features.measure(ctx, fact), currency, is_fact=True)
            facts.append(item)
        states[tag_id] = state
        missing_by_tag[tag_id] = sorted(missing)
        reason = render_reason(tag["reason"], _reason_values(evidence, facts))
        results[tag_id] = TagResult(tag, state, evidence, facts, sorted(missing), reason,
                                    rule_text(tag["rule"], currency))
    return OrderedDict((tag["id"], results[tag["id"]]) for tag in taxonomy.tags)

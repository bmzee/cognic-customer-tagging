"""Load and validate taxonomy/tags.json.

The rule language is deliberately small. A tag's rule is a tree of
{"all": [...]} / {"any": [...]} nodes whose leaves are conditions:

    {"id": "salary_months", "description": "months with a salary credit",
     "metric": "months_where", "filter": {...}, "window": {"months": 6},
     "monthly": {"measure": "count", "op": ">=", "value": 1},
     "op": ">=", "value": 6}

Metrics
    count, sum, max, count_per_month, sum_per_month   filter + window
    months_where   filter + month window + monthly {measure, op, value};
                   measure is count, sum, net_flow, net_flow_ratio or
                   deviation_from_median
    distinct       number of distinct values of field (filter + window)
    share          part matching filter, within transactions matching of,
                   by count or amount (filter + of + by + window)
    ratio          numerator / denominator, each a scalar metric with its
                   own filter and window; min_denominator guards thin history
    tenure_days    days since the account was opened
    tag            whether another tag matched (op "==", value true/false)

"facts" use the same leaf shape without op/value: they are extra evidence
shown in the reason, never part of the decision.

Validation refuses unknown keys, unknown fields, protected traits, age and
proxy categories (see engine/policy.py), and checks that each tag's declared
"fields" equal the fields its rule actually reads.
"""

import json
import re
from collections import OrderedDict
from decimal import Decimal, InvalidOperation

from . import policy
from . import windows


class TaxonomyError(ValueError):
    pass


OPS = (">=", ">", "<=", "<", "==")
SCALAR_METRICS = ("count", "sum", "max", "count_per_month", "sum_per_month")
METRICS = SCALAR_METRICS + ("months_where", "distinct", "share", "ratio", "tenure_days", "tag")
MONTHLY_MEASURES = ("count", "sum", "net_flow", "net_flow_ratio", "deviation_from_median")
FORMATS = ("count", "amount", "percent", "times", "rate", "days", "yesno")
DEFAULT_FORMAT = {
    "count": "count",
    "sum": "amount",
    "max": "amount",
    "count_per_month": "rate",
    "sum_per_month": "amount",
    "months_where": "count",
    "distinct": "count",
    "share": "percent",
    "ratio": "times",
    "tenure_days": "days",
    "tag": "yesno",
}
AMOUNT_METRICS = ("sum", "max", "sum_per_month")
AMOUNT_MEASURES = ("sum", "net_flow", "net_flow_ratio", "deviation_from_median")

TAG_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
COND_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")
REF_RE = re.compile(r"^([a-z][a-z0-9_]*)(?:\.(threshold|numerator|denominator))?$")

_COMMON_KEYS = {"id", "description", "metric", "format"}
_LEAF_KEYS = {
    "count": {"filter", "window"},
    "sum": {"filter", "window"},
    "max": {"filter", "window"},
    "count_per_month": {"filter", "window"},
    "sum_per_month": {"filter", "window"},
    "months_where": {"filter", "window", "monthly"},
    "distinct": {"field", "filter", "window"},
    "share": {"filter", "of", "by", "window"},
    "ratio": {"numerator", "denominator", "min_denominator"},
    "tenure_days": set(),
    "tag": {"tag"},
}
_TAG_KEYS = {"id", "name", "group", "description", "fields", "rule", "facts", "reason"}
_TOP_KEYS = {"schema_version", "taxonomy_version", "description", "settings", "fairness", "tags"}


def _fail(where, message):
    raise TaxonomyError("{}: {}".format(where, message))


def _number(where, value, allow_negative=True, allow_string=False):
    allowed = (int, float, str) if allow_string else (int, float)
    if isinstance(value, bool) or not isinstance(value, allowed):
        _fail(where, "expected a number, got {!r}".format(value))
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        _fail(where, "expected a number, got {!r}".format(value))
    if not number.is_finite() or (not allow_negative and number < 0):
        _fail(where, "number out of range: {!r}".format(value))
    return number


def _check_keys(where, obj, allowed, required=()):
    if not isinstance(obj, dict):
        _fail(where, "expected an object")
    unknown = sorted(set(obj) - set(allowed))
    if unknown:
        _fail(where, "unknown key(s): {}".format(", ".join(unknown)))
    missing = [k for k in required if k not in obj]
    if missing:
        _fail(where, "missing key(s): {}".format(", ".join(missing)))


def _check_window(where, window, months_only=False):
    if not isinstance(window, dict):
        _fail(where, "window must be an object")
    keys = set(window)
    if keys in ({"days"}, {"days", "offset_days"}):
        if months_only:
            _fail(where, "this metric needs a month window")
        size_key, offset_key, limit = "days", "offset_days", 3660
    elif keys in ({"months"}, {"months", "offset_months"}):
        size_key, offset_key, limit = "months", "offset_months", 120
    else:
        _fail(where, "window must be {days[, offset_days]} or {months[, offset_months]}")
    size = window[size_key]
    if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= limit:
        _fail(where, "window size must be an integer from 1 to {}".format(limit))
    offset = window.get(offset_key, 0)
    if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= limit:
        _fail(where, "window offset must be an integer from 0 to {}".format(limit))


def _check_filter(where, flt):
    if not isinstance(flt, dict):
        _fail(where, "filter must be an object")
    for field, matcher in flt.items():
        reason = policy.protected_reason(field)
        if reason:
            _fail(where, "filter field {!r} {}".format(field, reason))
        if field not in policy.FILTER_FIELDS:
            _fail(where, "unknown filter field {!r}".format(field))
        if field in policy.BOOLEAN_FILTER_FIELDS:
            if not isinstance(matcher, bool):
                _fail(where, "{} must be true or false".format(field))
            continue
        upper = field in ("currency", "txn_country")
        if isinstance(matcher, dict):
            _check_keys(where, matcher, {"not_in"}, ("not_in",))
            values, including = matcher["not_in"], False
        elif isinstance(matcher, list):
            values, including = matcher, True
        else:
            values, including = [matcher], True
        if not isinstance(values, list) or not values:
            _fail(where, "{} needs a non-empty list of values".format(field))
        for value in values:
            if not isinstance(value, str) or not value:
                _fail(where, "{} values must be non-empty strings".format(field))
            canonical = value.upper() if upper else value.lower()
            if value != canonical:
                _fail(where, "{} value {!r} must be written as {!r}".format(field, value, canonical))
            if field == "direction" and value not in ("credit", "debit"):
                _fail(where, "direction must be credit or debit")
            if including and field == "category":
                reason = policy.proxy_category_reason(value)
                if reason:
                    _fail(where, "category {!r} {}".format(value, reason))


def _filter_fields(flt):
    fields = set()
    for field in flt or {}:
        if field == "is_foreign_currency":
            fields.update(("transactions.currency", "customers.home_currency"))
        elif field == "is_foreign_country":
            fields.update(("transactions.txn_country", "customers.home_country"))
        else:
            fields.add("transactions." + field)
    return fields


def _check_scalar_spec(where, spec):
    _check_keys(where, spec, {"metric", "filter", "window", "format"}, ("metric", "window"))
    if spec["metric"] not in SCALAR_METRICS:
        _fail(where, "ratio parts must use one of: {}".format(", ".join(SCALAR_METRICS)))
    if "format" in spec and spec["format"] not in FORMATS:
        _fail(where, "unknown format {!r}".format(spec["format"]))
    _check_filter(where, spec.get("filter", {}))
    _check_window(where, spec["window"])


def _scalar_fields(spec):
    fields = {"transactions.posted_date"} | _filter_fields(spec.get("filter"))
    if spec["metric"] in AMOUNT_METRICS:
        fields.update(("transactions.amount", "transactions.currency"))
    return fields


def _check_leaf(where, leaf, is_fact):
    if not isinstance(leaf, dict):
        _fail(where, "expected an object")
    metric = leaf.get("metric")
    if metric not in METRICS:
        _fail(where, "unknown metric {!r}".format(metric))
    allowed = _COMMON_KEYS | _LEAF_KEYS[metric]
    if not is_fact:
        allowed = allowed | {"op", "value"}
    required = ["id", "description", "metric"] + ([] if is_fact else ["op", "value"])
    if metric in SCALAR_METRICS or metric in ("months_where", "distinct", "share"):
        required.append("window")
    if metric == "months_where":
        required.append("monthly")
    if metric == "distinct":
        required.append("field")
    if metric == "share":
        required.extend(("of", "by"))
    if metric == "ratio":
        required.extend(("numerator", "denominator"))
    if metric == "tag":
        required.append("tag")
    _check_keys(where, leaf, allowed, required)

    if not isinstance(leaf["id"], str) or not COND_ID_RE.match(leaf["id"]):
        _fail(where, "condition id {!r} must match {}".format(leaf.get("id"), COND_ID_RE.pattern))
    where = "{} [{}]".format(where, leaf["id"])
    if not isinstance(leaf["description"], str) or not leaf["description"].strip():
        _fail(where, "description must be a non-empty string")
    if "format" in leaf and leaf["format"] not in FORMATS:
        _fail(where, "unknown format {!r}".format(leaf["format"]))

    if not is_fact:
        if leaf["op"] not in OPS:
            _fail(where, "unknown op {!r}".format(leaf["op"]))
        if metric == "tag":
            if leaf["op"] != "==" or not isinstance(leaf["value"], bool):
                _fail(where, "a tag condition is op '==' with value true or false")
        else:
            _number(where, leaf["value"])

    if "filter" in leaf:
        _check_filter(where, leaf["filter"])
    if "window" in leaf:
        _check_window(where, leaf["window"], months_only=(metric == "months_where"))
    if metric == "months_where":
        monthly = leaf["monthly"]
        _check_keys(where, monthly, {"measure", "op", "value"}, ("measure", "op", "value"))
        if monthly["measure"] not in MONTHLY_MEASURES:
            _fail(where, "unknown monthly measure {!r}".format(monthly["measure"]))
        if monthly["op"] not in OPS:
            _fail(where, "unknown monthly op {!r}".format(monthly["op"]))
        _number(where, monthly["value"])
    if metric == "distinct":
        field = leaf["field"]
        reason = policy.protected_reason(field)
        if reason:
            _fail(where, "field {!r} {}".format(field, reason))
        if field not in policy.DISTINCT_FIELDS:
            _fail(where, "distinct field must be one of: {}".format(", ".join(sorted(policy.DISTINCT_FIELDS))))
    if metric == "share":
        _check_filter(where, leaf["of"])
        if leaf["by"] not in ("count", "amount"):
            _fail(where, "share 'by' must be count or amount")
    if metric == "ratio":
        _check_scalar_spec(where + " numerator", leaf["numerator"])
        _check_scalar_spec(where + " denominator", leaf["denominator"])
        if "min_denominator" in leaf:
            _number(where, leaf["min_denominator"], allow_negative=False)
    if metric == "tag":
        if not isinstance(leaf["tag"], str) or not TAG_ID_RE.match(leaf["tag"]):
            _fail(where, "tag must be a tag id")


def _leaf_fields(leaf):
    metric = leaf["metric"]
    if metric in SCALAR_METRICS:
        return _scalar_fields(leaf)
    if metric == "months_where":
        fields = {"transactions.posted_date"} | _filter_fields(leaf.get("filter"))
        measure = leaf["monthly"]["measure"]
        if measure in AMOUNT_MEASURES:
            fields.update(("transactions.amount", "transactions.currency"))
        if measure in ("net_flow", "net_flow_ratio"):
            fields.add("transactions.direction")
        return fields
    if metric == "distinct":
        return {"transactions.posted_date", "transactions." + leaf["field"]} | _filter_fields(leaf.get("filter"))
    if metric == "share":
        fields = {"transactions.posted_date"} | _filter_fields(leaf.get("filter")) | _filter_fields(leaf["of"])
        if leaf["by"] == "amount":
            fields.update(("transactions.amount", "transactions.currency"))
        return fields
    if metric == "ratio":
        return _scalar_fields(leaf["numerator"]) | _scalar_fields(leaf["denominator"])
    if metric == "tenure_days":
        return {"customers.account_open_date"}
    return set()


def iter_leaves(node):
    """Yield every condition leaf of a rule tree, in order."""
    if "all" in node or "any" in node:
        for child in node.get("all", node.get("any")):
            for leaf in iter_leaves(child):
                yield leaf
    else:
        yield node


def _check_rule(where, node, depth=0):
    if depth > 6:
        _fail(where, "rule nesting is too deep")
    if not isinstance(node, dict):
        _fail(where, "rule nodes must be objects")
    if "all" in node or "any" in node:
        if len(node) != 1:
            _fail(where, "a rule node has exactly one key, 'all' or 'any'")
        children = node.get("all", node.get("any"))
        if not isinstance(children, list) or not children:
            _fail(where, "'all'/'any' need a non-empty list")
        for child in children:
            _check_rule(where, child, depth + 1)
    else:
        _check_leaf(where, node, is_fact=False)


class Taxonomy(object):
    def __init__(self, raw, tags, order, base_currency, fx_rates, derived_fields):
        self.raw = raw
        self.version = raw["taxonomy_version"]
        self.tags = tags
        self.by_id = OrderedDict((t["id"], t) for t in tags)
        self.order = order
        self.base_currency = base_currency
        self.fx_rates = fx_rates
        self.derived_fields = derived_fields


def _check_reason(where, tag, leaves_by_id, facts_by_id):
    template = tag["reason"]
    if not isinstance(template, str) or not template.strip():
        _fail(where, "reason must be a non-empty string")
    stripped = PLACEHOLDER_RE.sub("", template)
    if "{" in stripped or "}" in stripped:
        _fail(where, "reason has an unbalanced brace")
    for ref in PLACEHOLDER_RE.findall(template):
        match = REF_RE.match(ref)
        if not match:
            _fail(where, "reason placeholder {{{}}} is not valid".format(ref))
        name, part = match.group(1), match.group(2)
        leaf = leaves_by_id.get(name) or facts_by_id.get(name)
        if leaf is None:
            _fail(where, "reason placeholder {{{}}} names no condition or fact".format(ref))
        if part == "threshold" and name not in leaves_by_id:
            _fail(where, "facts have no threshold: {{{}}}".format(ref))
        if part in ("numerator", "denominator") and leaf["metric"] not in ("share", "ratio"):
            _fail(where, "only share and ratio have a {}: {{{}}}".format(part, ref))


def load_taxonomy_data(raw, source="taxonomy"):
    _check_keys(source, raw, _TOP_KEYS, ("schema_version", "taxonomy_version", "settings", "fairness", "tags"))
    if raw["schema_version"] != "1":
        _fail(source, "unsupported schema_version {!r}".format(raw["schema_version"]))

    settings = raw["settings"]
    _check_keys(source + " settings", settings, {"base_currency", "fx_rates_to_base", "notes"},
                ("base_currency", "fx_rates_to_base"))
    base = settings["base_currency"]
    if not isinstance(base, str) or not CURRENCY_RE.match(base):
        _fail(source, "base_currency must be a 3-letter code")
    fx_rates = {}
    for code, rate in sorted(settings["fx_rates_to_base"].items()):
        if not CURRENCY_RE.match(code):
            _fail(source, "bad currency code {!r}".format(code))
        if not isinstance(rate, str):
            _fail(source, "write rates as strings, e.g. \"1.10\" (exact decimals)")
        value = _number(source + " fx " + code, rate, allow_negative=False, allow_string=True)
        if value <= 0:
            _fail(source, "rate for {} must be positive".format(code))
        fx_rates[code] = value
    if fx_rates.get(base) != Decimal(1):
        _fail(source, "the base currency must have rate \"1\"")

    fairness = raw["fairness"]
    _check_keys(source + " fairness", fairness, {"excluded_traits", "age", "proxies_avoided", "notes"},
                ("excluded_traits", "age", "proxies_avoided"))

    tags = raw["tags"]
    if not isinstance(tags, list) or not tags:
        _fail(source, "tags must be a non-empty list")
    seen = set()
    for index, tag in enumerate(tags):
        where = "{} tag #{}".format(source, index + 1)
        _check_keys(where, tag, _TAG_KEYS, ("id", "name", "group", "description", "fields", "rule", "reason"))
        if not isinstance(tag["id"], str) or not TAG_ID_RE.match(tag["id"]):
            _fail(where, "tag id {!r} must match {}".format(tag.get("id"), TAG_ID_RE.pattern))
        where = "{} ({})".format(source, tag["id"])
        if tag["id"] in seen:
            _fail(where, "duplicate tag id")
        seen.add(tag["id"])
        for key in ("name", "group", "description"):
            if not isinstance(tag[key], str) or not tag[key].strip():
                _fail(where, "{} must be a non-empty string".format(key))
        if not isinstance(tag["fields"], list) or not all(isinstance(f, str) for f in tag["fields"]):
            _fail(where, "fields must be a list of strings")
        for field in tag["fields"]:
            reason = policy.protected_reason(field)
            if reason:
                _fail(where, "field {!r} {}".format(field, reason))
        _check_rule(where, tag["rule"])
        facts = tag.get("facts", [])
        if not isinstance(facts, list):
            _fail(where, "facts must be a list")
        for fact in facts:
            _check_leaf(where + " fact", fact, is_fact=True)
            if fact["metric"] == "tag":
                _fail(where, "facts cannot be tag conditions")
        leaves = list(iter_leaves(tag["rule"]))
        ids = [leaf["id"] for leaf in leaves] + [fact["id"] for fact in facts]
        if len(ids) != len(set(ids)):
            _fail(where, "condition and fact ids must be unique within a tag")
        _check_reason(where, tag, OrderedDict((l["id"], l) for l in leaves),
                      OrderedDict((f["id"], f) for f in facts))

    by_id = OrderedDict((t["id"], t) for t in tags)
    deps = OrderedDict()
    for tag in tags:
        refs = []
        for leaf in iter_leaves(tag["rule"]):
            if leaf["metric"] == "tag":
                if leaf["tag"] not in by_id:
                    _fail("{} ({})".format(source, tag["id"]), "depends on unknown tag {!r}".format(leaf["tag"]))
                if leaf["tag"] == tag["id"]:
                    _fail("{} ({})".format(source, tag["id"]), "a tag cannot depend on itself")
                refs.append(leaf["tag"])
        deps[tag["id"]] = refs

    order = []
    state = {}

    def visit(tag_id, path):
        if state.get(tag_id) == "done":
            return
        if state.get(tag_id) == "active":
            _fail(source, "tag dependency cycle: {}".format(" -> ".join(path + [tag_id])))
        state[tag_id] = "active"
        for dep in deps[tag_id]:
            visit(dep, path + [tag_id])
        state[tag_id] = "done"
        order.append(tag_id)

    for tag in tags:
        visit(tag["id"], [])

    derived = {}
    for tag_id in order:
        tag = by_id[tag_id]
        fields = set()
        for leaf in list(iter_leaves(tag["rule"])) + list(tag.get("facts", [])):
            fields |= _leaf_fields(leaf)
            if leaf["metric"] == "tag":
                fields |= set(derived[leaf["tag"]])
        derived[tag_id] = sorted(fields)
        declared = sorted(set(tag["fields"]))
        if declared != derived[tag_id] or len(tag["fields"]) != len(declared):
            _fail(
                "{} ({})".format(source, tag_id),
                "declared fields {} do not match the fields the rule reads {}".format(
                    tag["fields"], derived[tag_id]
                ),
            )

    return Taxonomy(raw, tags, order, base, fx_rates, derived)


def load_taxonomy(path):
    with open(path, "r", encoding="utf-8") as handle:
        try:
            raw = json.load(handle, object_pairs_hook=_no_duplicate_keys)
        except ValueError as exc:
            raise TaxonomyError("{}: not valid JSON: {}".format(path, exc))
    return load_taxonomy_data(raw, source=str(path))


def _no_duplicate_keys(pairs):
    result = OrderedDict()
    for key, value in pairs:
        if key in result:
            raise TaxonomyError("duplicate JSON key {!r}".format(key))
        result[key] = value
    return result


def describe_window(window):
    return windows.describe(window)

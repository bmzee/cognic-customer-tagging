"""Load and validate taxonomy/tags.json and its reference tables.

The rule language is deliberately small. A tag's rule is a tree of
{"all": [...]} / {"any": [...]} nodes whose leaves are conditions:

    {"id": "salary_months", "description": "months with a salary credit",
     "metric": "months_where", "filter": {...}, "window": {"months": 6},
     "monthly": {"measure": "count", "op": ">=", "value": 1},
     "op": ">=", "value": 6}

Metrics
    count, sum, max, count_per_month, sum_per_month   filter + window
    months_where   filter + month window + monthly {measure, op, value};
                   measure is count, sum, net_flow, net_flow_ratio,
                   deviation_from_median, min_balance or end_balance
    distinct       number of distinct values of field (filter + window)
    share          part matching filter, within transactions matching of,
                   by count or amount (filter + of + by + window)
    ratio          numerator / denominator, each a scalar metric with its
                   own filter and window; min_denominator guards thin history
    tenure_days    days since the account was opened
    tag            whether another tag matched (op "==", value true/false)
    recurring      number of recurring streams (per counterparty) in a month
                   window: period_months, min_occurrences, amount_tolerance,
                   optional max_missed
    days_since_last  days since the last matching transaction in a day
                   window (the window length when there was none)
    balance        lowest, latest or average_month_end balance in a window

"facts" use the same leaf shape without op/value: they are extra evidence
shown in the reason, never part of the decision.

Validation refuses unknown keys, unknown fields, protected traits, age,
proxy categories and specific countries or currencies (see
engine/policy.py), and checks that each tag's declared "fields" equal the
fields its rule actually reads.

Version and hash: taxonomy_version is bumped on every change, and
content_hash is the SHA-256 of the canonical JSON of tags.json (without
content_hash and changelog) together with the two reference tables. The
loader refuses a file whose stored hash does not match its content, so a
rule cannot change without a new hash, and the changelog ties each hash to
one version.
"""

import hashlib
import json
import os
import re
from collections import OrderedDict
from decimal import Decimal, InvalidOperation

from . import aggregate
from . import policy
from . import reference
from . import windows


class TaxonomyError(ValueError):
    pass


SCHEMA_VERSION = "2"
OPS = (">=", ">", "<=", "<", "==")
SCALAR_METRICS = ("count", "sum", "max", "count_per_month", "sum_per_month")
METRICS = SCALAR_METRICS + ("months_where", "distinct", "share", "ratio", "tenure_days", "tag", "recurring",
                            "days_since_last", "balance")
MONTHLY_MEASURES = ("count", "sum", "net_flow", "net_flow_ratio", "deviation_from_median", "min_balance",
                    "end_balance")
BALANCE_MEASURES = ("lowest", "latest", "average_month_end")
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
    "recurring": "count",
    "days_since_last": "days",
    "balance": "amount",
}
AMOUNT_METRICS = ("sum", "max", "sum_per_month")
AMOUNT_MEASURES = ("sum", "net_flow", "net_flow_ratio", "deviation_from_median")

TAG_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
COND_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
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
    "recurring": {"filter", "window", "period_months", "min_occurrences", "amount_tolerance", "amount_floor",
                  "max_missed"},
    "days_since_last": {"filter", "window"},
    "balance": {"measure", "window"},
}
_TAG_KEYS = {"id", "name", "group", "description", "polarity", "fields", "rule", "facts", "reason", "limitations",
             "bank_policy_decides"}
POLARITIES = ("benefit", "burden", "neutral")
_TOP_KEYS = {"schema_version", "taxonomy_version", "content_hash", "changelog", "description", "settings",
             "fairness", "governance", "groups", "exclusive_groups", "tags"}
_HASH_EXCLUDED = ("content_hash", "changelog")

TAXONOMY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "taxonomy")
COUNTERPARTIES_FILE = "counterparties.json"
MERCHANT_CODES_FILE = "merchant_codes.json"


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


def _int(where, value, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        _fail(where, "expected an integer from {} to {}, got {!r}".format(low, high, value))
    return value


def _check_keys(where, obj, allowed, required=()):
    if not isinstance(obj, dict):
        _fail(where, "expected an object")
    unknown = sorted(set(obj) - set(allowed))
    if unknown:
        _fail(where, "unknown key(s): {}".format(", ".join(unknown)))
    missing = [k for k in required if k not in obj]
    if missing:
        _fail(where, "missing key(s): {}".format(", ".join(missing)))


def _check_window(where, window, months_only=False, days_only=False):
    if not isinstance(window, dict):
        _fail(where, "window must be an object")
    keys = set(window)
    if keys in ({"days"}, {"days", "offset_days"}):
        if months_only:
            _fail(where, "this metric needs a month window")
        size_key, offset_key, limit = "days", "offset_days", 3660
    elif keys in ({"months"}, {"months", "offset_months"}):
        if days_only:
            _fail(where, "this metric needs a day window")
        size_key, offset_key, limit = "months", "offset_months", 120
    else:
        _fail(where, "window must be {days[, offset_days]} or {months[, offset_months]}")
    size = window[size_key]
    if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= limit:
        _fail(where, "window size must be an integer from 1 to {}".format(limit))
    offset = window.get(offset_key, 0)
    if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= limit:
        _fail(where, "window offset must be an integer from 0 to {}".format(limit))


def window_months(window):
    """How many calendar months back a window can reach (for history_months)."""
    if "months" in window:
        return window["months"] + window.get("offset_months", 0) + 1
    return (window["days"] + window.get("offset_days", 0)) // 28 + 2


class _Context(object):
    def __init__(self, kinds):
        self.kinds = kinds


def _check_filter(where, flt, ctx):
    if not isinstance(flt, dict):
        _fail(where, "filter must be an object")
    for field, matcher in flt.items():
        reason = policy.protected_reason(field)
        if reason:
            _fail(where, "filter field {!r} {}".format(field, reason))
        if field in policy.VALUE_SELECTION_REFUSED:
            _fail(where, "filter field {!r} {}".format(field, policy.VALUE_SELECTION_REFUSED[field]))
        if field not in policy.FILTER_FIELDS:
            _fail(where, "unknown filter field {!r}".format(field))
        if field in policy.BOOLEAN_FILTER_FIELDS:
            if not isinstance(matcher, bool):
                _fail(where, "{} must be true or false".format(field))
            continue
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
            canonical = value.upper() if field == "counterparty" else value.lower()
            if value != canonical:
                _fail(where, "{} value {!r} must be written as {!r}".format(field, value, canonical))
            if field == "direction" and value not in ("credit", "debit"):
                _fail(where, "direction must be credit or debit")
            if field == "counterparty_kind" and value not in ctx.kinds:
                _fail(where, "unknown counterparty kind {!r}".format(value))
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
        elif field == "counterparty_kind":
            fields.add("transactions.counterparty")
        else:
            fields.add("transactions." + field)
    return fields


def _check_scalar_spec(where, spec, ctx):
    if spec.get("metric") == "balance":
        _check_keys(where, spec, {"metric", "measure", "window", "format"}, ("metric", "measure", "window"))
        if spec["measure"] not in BALANCE_MEASURES:
            _fail(where, "balance measure must be one of: {}".format(", ".join(BALANCE_MEASURES)))
        _check_window(where, spec["window"], months_only=spec["measure"] == "average_month_end")
        if "format" in spec and spec["format"] not in FORMATS:
            _fail(where, "unknown format {!r}".format(spec["format"]))
        return
    _check_keys(where, spec, {"metric", "filter", "window", "format"}, ("metric", "window"))
    if spec["metric"] not in SCALAR_METRICS:
        _fail(where, "ratio parts must use balance or one of: {}".format(", ".join(SCALAR_METRICS)))
    if "format" in spec and spec["format"] not in FORMATS:
        _fail(where, "unknown format {!r}".format(spec["format"]))
    _check_filter(where, spec.get("filter", {}), ctx)
    _check_window(where, spec["window"])


def _scalar_fields(spec):
    if spec["metric"] == "balance":
        return {"transactions.posted_date", "transactions.balance_after"}
    fields = {"transactions.posted_date"} | _filter_fields(spec.get("filter"))
    if spec["metric"] in AMOUNT_METRICS:
        fields.update(("transactions.amount", "transactions.currency"))
    return fields


def _check_leaf(where, leaf, is_fact, ctx):
    if not isinstance(leaf, dict):
        _fail(where, "expected an object")
    metric = leaf.get("metric")
    if metric not in METRICS:
        _fail(where, "unknown metric {!r}".format(metric))
    allowed = _COMMON_KEYS | _LEAF_KEYS[metric]
    if not is_fact:
        allowed = allowed | {"op", "value"}
    required = ["id", "description", "metric"] + ([] if is_fact else ["op", "value"])
    if metric in SCALAR_METRICS or metric in ("months_where", "distinct", "share", "recurring", "days_since_last",
                                              "balance"):
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
    if metric == "recurring":
        required.extend(("period_months", "min_occurrences", "amount_tolerance"))
    if metric == "balance":
        required.append("measure")
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
        _check_filter(where, leaf["filter"], ctx)
    if "window" in leaf:
        _check_window(where, leaf["window"],
                      months_only=metric in ("months_where", "recurring") or
                      (metric == "balance" and leaf.get("measure") == "average_month_end"),
                      days_only=metric == "days_since_last")
    if metric == "months_where":
        monthly = leaf["monthly"]
        _check_keys(where, monthly, {"measure", "op", "value"}, ("measure", "op", "value"))
        if monthly["measure"] not in MONTHLY_MEASURES:
            _fail(where, "unknown monthly measure {!r}".format(monthly["measure"]))
        if monthly["measure"] in ("min_balance", "end_balance") and leaf.get("filter"):
            _fail(where, "balance measures read the balance, not a filter")
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
        _check_filter(where, leaf["of"], ctx)
        if leaf["by"] not in ("count", "amount"):
            _fail(where, "share 'by' must be count or amount")
    if metric == "ratio":
        _check_scalar_spec(where + " numerator", leaf["numerator"], ctx)
        _check_scalar_spec(where + " denominator", leaf["denominator"], ctx)
        if "min_denominator" in leaf:
            _number(where, leaf["min_denominator"], allow_negative=False)
    if metric == "tag":
        if not isinstance(leaf["tag"], str) or not TAG_ID_RE.match(leaf["tag"]):
            _fail(where, "tag must be a tag id")
    if metric == "recurring":
        period = _int(where + " period_months", leaf["period_months"], 1, 12)
        minimum = _int(where + " min_occurrences", leaf["min_occurrences"], 2, 120)
        _int(where + " max_missed", leaf.get("max_missed", 0), 0, 12)
        tolerance = _number(where + " amount_tolerance", leaf["amount_tolerance"], allow_negative=False)
        if tolerance > 1:
            _fail(where, "amount_tolerance is a fraction from 0 to 1")
        if "amount_floor" in leaf:
            _number(where + " amount_floor", leaf["amount_floor"], allow_negative=False)
        if (minimum - 1) * period >= leaf["window"]["months"] + period:
            _fail(where, "min_occurrences cannot fit in the window")
    if metric == "balance" and leaf["measure"] not in BALANCE_MEASURES:
        _fail(where, "balance measure must be one of: {}".format(", ".join(BALANCE_MEASURES)))


def _leaf_fields(leaf):
    metric = leaf["metric"]
    if metric in SCALAR_METRICS:
        return _scalar_fields(leaf)
    if metric == "months_where":
        measure = leaf["monthly"]["measure"]
        if measure in ("min_balance", "end_balance"):
            return {"transactions.posted_date", "transactions.balance_after"}
        fields = {"transactions.posted_date"} | _filter_fields(leaf.get("filter"))
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
    if metric == "recurring":
        return ({"transactions.posted_date", "transactions.amount", "transactions.currency",
                 "transactions.counterparty"} | _filter_fields(leaf.get("filter")))
    if metric == "days_since_last":
        return {"transactions.posted_date"} | _filter_fields(leaf.get("filter"))
    if metric == "balance":
        return {"transactions.posted_date", "transactions.balance_after"}
    return set()


def iter_leaves(node):
    """Yield every condition leaf of a rule tree, in order."""
    if "all" in node or "any" in node:
        for child in node.get("all", node.get("any")):
            for leaf in iter_leaves(child):
                yield leaf
    else:
        yield node


def _check_rule(where, node, ctx, depth=0):
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
            _check_rule(where, child, ctx, depth + 1)
    else:
        _check_leaf(where, node, False, ctx)


def _request_features(features, tag_id, leaf, leaf_features):
    metric = leaf["metric"]
    flt = leaf.get("filter", {})
    if metric in SCALAR_METRICS or metric in ("days_since_last",):
        leaf_features[(tag_id, leaf["id"], "main")] = features.request([flt])
    elif metric == "months_where":
        if leaf["monthly"]["measure"] in ("min_balance", "end_balance"):
            leaf_features[(tag_id, leaf["id"], "main")] = features.request([], balance=True)
        else:
            leaf_features[(tag_id, leaf["id"], "main")] = features.request([flt])
    elif metric == "distinct":
        leaf_features[(tag_id, leaf["id"], "main")] = features.request([flt], distinct_field=leaf["field"])
    elif metric == "share":
        leaf_features[(tag_id, leaf["id"], "of")] = features.request([leaf["of"]])
        leaf_features[(tag_id, leaf["id"], "part")] = features.request([leaf["of"], flt])
    elif metric == "ratio":
        for role in ("numerator", "denominator"):
            part = leaf[role]
            if part["metric"] == "balance":
                leaf_features[(tag_id, leaf["id"], role)] = features.request([], balance=True)
            else:
                leaf_features[(tag_id, leaf["id"], role)] = features.request([part.get("filter", {})])
    elif metric == "recurring":
        leaf_features[(tag_id, leaf["id"], "main")] = features.request([flt], streams=True)
    elif metric == "balance":
        leaf_features[(tag_id, leaf["id"], "main")] = features.request([], balance=True)


class Taxonomy(object):
    def __init__(self, raw, tags, order, base_currency, fx_rates, derived_fields, counterparties, merchant_codes,
                 content_hash, specs, leaf_features, groups, exclusive_groups, history_months, lifecycle_months):
        self.raw = raw
        self.version = raw["taxonomy_version"]
        self.content_hash = content_hash
        self.tags = tags
        self.by_id = OrderedDict((t["id"], t) for t in tags)
        self.order = order
        self.base_currency = base_currency
        self.fx_rates = fx_rates
        self.derived_fields = derived_fields
        self.counterparties = counterparties
        self.merchant_codes = merchant_codes
        self.specs = specs
        self.leaf_features = leaf_features
        self.groups = groups
        self.exclusive_groups = exclusive_groups
        self.exclusive_of = OrderedDict()
        for group in exclusive_groups:
            for tag_id in group["priority"]:
                self.exclusive_of[tag_id] = group["id"]
        self.history_months = history_months
        self.lifecycle_months = lifecycle_months
        self.governance = raw["governance"]
        self.rule_texts = {}
        self.leaf_thresholds = {}


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


def compute_content_hash(raw, counterparties_raw, merchant_codes_raw):
    """sha256 over the canonical JSON of the taxonomy (minus content_hash and
    changelog) and both reference tables."""
    body = OrderedDict((k, v) for k, v in raw.items() if k not in _HASH_EXCLUDED)
    payload = aggregate.canonical_json({
        "tags": body, "counterparties": counterparties_raw, "merchant_codes": merchant_codes_raw,
    })
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _check_governance(source, governance):
    _check_keys(source + " governance", governance,
                {"owner", "review_date", "intended_use", "prohibited_uses", "notes"},
                ("owner", "review_date", "intended_use", "prohibited_uses"))
    for key in ("owner", "intended_use"):
        if not isinstance(governance[key], str) or not governance[key].strip():
            _fail(source, "governance {} must be a non-empty string".format(key))
    if not isinstance(governance["review_date"], str) or not DATE_RE.match(governance["review_date"]):
        _fail(source, "governance review_date must be YYYY-MM-DD")
    uses = governance["prohibited_uses"]
    if not isinstance(uses, list) or len(uses) < 4 or not all(isinstance(u, str) and u for u in uses):
        _fail(source, "governance prohibited_uses must list the prohibited uses")
    text = " ".join(uses).lower()
    for needed in ("credit", "pricing", "fraud", "automated decision"):
        if needed not in text:
            _fail(source, "governance prohibited_uses must cover {}".format(needed))


def _check_changelog(source, raw):
    changelog = raw.get("changelog", [])
    if not isinstance(changelog, list):
        _fail(source, "changelog must be a list")
    seen_versions = set()
    for index, entry in enumerate(changelog):
        where = "{} changelog #{}".format(source, index + 1)
        _check_keys(where, entry, {"version", "content_hash", "date", "summary"},
                    ("version", "content_hash", "date", "summary"))
        if not VERSION_RE.match(str(entry["version"])) or entry["version"] in seen_versions:
            _fail(where, "versions must be unique x.y.z")
        seen_versions.add(entry["version"])
        if not HASH_RE.match(str(entry["content_hash"])):
            _fail(where, "content_hash must be sha256:<64 hex>")
    return changelog


def load_taxonomy_data(raw, source="taxonomy", counterparties_raw=None, merchant_codes_raw=None,
                       verify_hash=True):
    """Validate a parsed tags.json. Reference tables default to the files in taxonomy/."""
    if counterparties_raw is None:
        counterparties_raw = reference.load_json(os.path.join(TAXONOMY_DIR, COUNTERPARTIES_FILE))
    if merchant_codes_raw is None:
        merchant_codes_raw = reference.load_json(os.path.join(TAXONOMY_DIR, MERCHANT_CODES_FILE))
    try:
        counterparties = reference.Counterparties(counterparties_raw)
        merchant_codes = reference.MerchantCodes(merchant_codes_raw)
    except reference.ReferenceTableError as exc:
        raise TaxonomyError(str(exc))
    ctx = _Context(counterparties.kinds)

    _check_keys(source, raw, _TOP_KEYS,
                ("schema_version", "taxonomy_version", "settings", "fairness", "governance", "groups",
                 "exclusive_groups", "tags"))
    if raw["schema_version"] != SCHEMA_VERSION:
        _fail(source, "unsupported schema_version {!r}".format(raw["schema_version"]))
    if not isinstance(raw["taxonomy_version"], str) or not VERSION_RE.match(raw["taxonomy_version"]):
        _fail(source, "taxonomy_version must be x.y.z")

    content_hash = compute_content_hash(raw, counterparties_raw, merchant_codes_raw)
    if verify_hash and "content_hash" in raw and raw["content_hash"] != content_hash:
        _fail(source, "content_hash does not match the content ({}); bump taxonomy_version, add a changelog "
                      "entry and store the new hash (python3 -m engine --taxonomy-hash)".format(content_hash))
    changelog = _check_changelog(source, raw)
    if verify_hash and "content_hash" in raw:
        latest = changelog[-1] if changelog else None
        if latest is None or latest["version"] != raw["taxonomy_version"] or latest["content_hash"] != content_hash:
            _fail(source, "the last changelog entry must record this taxonomy_version and content_hash")

    settings = raw["settings"]
    _check_keys(source + " settings", settings,
                {"base_currency", "fx_rates_to_base", "history_months", "lifecycle_months", "notes"},
                ("base_currency", "fx_rates_to_base", "history_months", "lifecycle_months"))
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
    history_months = _int(source + " history_months", settings["history_months"], 2, 120)
    lifecycle_months = _int(source + " lifecycle_months", settings["lifecycle_months"], 1, history_months)

    fairness = raw["fairness"]
    _check_keys(source + " fairness", fairness, {"excluded_traits", "age", "proxies_avoided", "notes"},
                ("excluded_traits", "age", "proxies_avoided"))
    _check_governance(source, raw["governance"])

    groups = OrderedDict()
    if not isinstance(raw["groups"], list) or not raw["groups"]:
        _fail(source, "groups must be a non-empty list")
    for group in raw["groups"]:
        _check_keys(source + " group", group, {"id", "name", "description"}, ("id", "name", "description"))
        if not TAG_ID_RE.match(str(group["id"])) or group["id"] in groups:
            _fail(source, "group ids must be unique tag-style ids")
        groups[group["id"]] = group

    tags = raw["tags"]
    if not isinstance(tags, list) or not tags:
        _fail(source, "tags must be a non-empty list")
    seen = set()
    for index, tag in enumerate(tags):
        where = "{} tag #{}".format(source, index + 1)
        _check_keys(where, tag, _TAG_KEYS,
                    ("id", "name", "group", "description", "polarity", "fields", "rule", "reason", "limitations"))
        if not isinstance(tag["id"], str) or not TAG_ID_RE.match(tag["id"]):
            _fail(where, "tag id {!r} must match {}".format(tag.get("id"), TAG_ID_RE.pattern))
        where = "{} ({})".format(source, tag["id"])
        if tag["id"] in seen:
            _fail(where, "duplicate tag id")
        seen.add(tag["id"])
        for key in ("name", "group", "description"):
            if not isinstance(tag[key], str) or not tag[key].strip():
                _fail(where, "{} must be a non-empty string".format(key))
        for key in ("id", "name"):
            reason = policy.protected_reason(tag[key])
            if reason:
                _fail(where, "tag {} {}".format(key, reason))
        if tag["group"] not in groups:
            _fail(where, "unknown group {!r}".format(tag["group"]))
        if tag["polarity"] not in POLARITIES:
            _fail(where, "polarity must be one of: {}".format(", ".join(POLARITIES)))
        if not isinstance(tag["limitations"], list) or not tag["limitations"] or \
                not all(isinstance(x, str) and x.strip() for x in tag["limitations"]):
            _fail(where, "limitations must be a non-empty list of strings")
        if "bank_policy_decides" in tag and not isinstance(tag["bank_policy_decides"], bool):
            _fail(where, "bank_policy_decides must be true or false")
        if not isinstance(tag["fields"], list) or not all(isinstance(f, str) for f in tag["fields"]):
            _fail(where, "fields must be a list of strings")
        for field in tag["fields"]:
            reason = policy.protected_reason(field)
            if reason:
                _fail(where, "field {!r} {}".format(field, reason))
        _check_rule(where, tag["rule"], ctx)
        facts = tag.get("facts", [])
        if not isinstance(facts, list):
            _fail(where, "facts must be a list")
        for fact in facts:
            _check_leaf(where + " fact", fact, True, ctx)
            if fact["metric"] == "tag":
                _fail(where, "facts cannot be tag conditions")
        leaves = list(iter_leaves(tag["rule"]))
        ids = [leaf["id"] for leaf in leaves] + [fact["id"] for fact in facts]
        if len(ids) != len(set(ids)):
            _fail(where, "condition and fact ids must be unique within a tag")
        _check_reason(where, tag, OrderedDict((l["id"], l) for l in leaves),
                      OrderedDict((f["id"], f) for f in facts))
        for leaf in leaves + facts:
            for window in [leaf.get("window")] + [leaf.get(p, {}).get("window") for p in ("numerator", "denominator")
                                                  if isinstance(leaf.get(p), dict)]:
                if window and window_months(window) > history_months + 1:
                    _fail(where, "a window reaches further back than history_months allows")

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

    exclusive = []
    seen_in_group = set()
    if not isinstance(raw["exclusive_groups"], list):
        _fail(source, "exclusive_groups must be a list")
    for group in raw["exclusive_groups"]:
        _check_keys(source + " exclusive group", group, {"id", "description", "priority"},
                    ("id", "description", "priority"))
        priority = group["priority"]
        if not isinstance(priority, list) or len(priority) < 2:
            _fail(source, "an exclusive group needs at least two tags in priority order")
        for tag_id in priority:
            if tag_id not in by_id:
                _fail(source, "exclusive group {} names unknown tag {!r}".format(group["id"], tag_id))
            if tag_id in seen_in_group:
                _fail(source, "tag {!r} is in more than one exclusive group".format(tag_id))
            seen_in_group.add(tag_id)
        exclusive.append(group)

    features = aggregate.FeatureSet()
    leaf_features = {}
    for tag in tags:
        for leaf in list(iter_leaves(tag["rule"])) + list(tag.get("facts", [])):
            _request_features(features, tag["id"], leaf, leaf_features)

    return Taxonomy(raw, tags, order, base, fx_rates, derived, counterparties, merchant_codes, content_hash,
                    features.build(), leaf_features, groups, exclusive, history_months, lifecycle_months)


def _no_duplicate_keys(pairs):
    result = OrderedDict()
    for key, value in pairs:
        if key in result:
            raise TaxonomyError("duplicate JSON key {!r}".format(key))
        result[key] = value
    return result


def read_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        try:
            return json.load(handle, object_pairs_hook=_no_duplicate_keys)
        except ValueError as exc:
            raise TaxonomyError("{}: not valid JSON: {}".format(path, exc))


def load_taxonomy(path, verify_hash=True):
    """Load tags.json and the reference tables beside it."""
    folder = os.path.dirname(os.path.abspath(path))
    raw = read_json(path)
    counterparties = read_json(os.path.join(folder, COUNTERPARTIES_FILE))
    merchant_codes = read_json(os.path.join(folder, MERCHANT_CODES_FILE))
    return load_taxonomy_data(raw, source=str(path), counterparties_raw=counterparties,
                              merchant_codes_raw=merchant_codes, verify_hash=verify_hash)


def describe_window(window):
    return windows.describe(window)

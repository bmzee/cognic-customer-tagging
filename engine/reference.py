"""Reference tables: counterparty normalisation and merchant category codes.

Both live next to tags.json and are part of the taxonomy's content hash, so
changing a mapping changes the hash just like changing a rule.

counterparties.json
    Cleans a raw counterparty string and maps it to a canonical counterparty
    and a kind (employer, business, person, merchant, biller, financial,
    own_account, unknown). Matching order: exact rules, then prefix rules from
    the longest pattern, then contains rules from the longest pattern. The
    result never depends on the order rows arrive in.

merchant_codes.json
    Four-digit ISO 18245-style codes mapped to this plugin's categories. A
    transaction's own category wins; the code fills in a missing category.
"""

import json
import re

from . import policy

_MATCHES = ("exact", "prefix", "contains")
_CODE_RE = re.compile(r"^[0-9]{4}$")
_CATEGORY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SPACES = re.compile(r"\s+")


class ReferenceTableError(ValueError):
    """A reference table is malformed."""


def _fail(source, message):
    raise ReferenceTableError("{}: {}".format(source, message))


def clean_counterparty(raw):
    """Upper case, collapse spaces, drop anything after '*' or '#', drop
    trailing all-digit tokens. Returns '' for an empty value."""
    text = _SPACES.sub(" ", (raw or "").strip().upper())
    for mark in ("*", "#"):
        if mark in text:
            text = text.split(mark, 1)[0].strip()
    tokens = text.split(" ") if text else []
    while len(tokens) > 1 and tokens[-1].isdigit():
        tokens.pop()
    return " ".join(tokens)


class Counterparties(object):
    def __init__(self, raw, source="counterparties"):
        if not isinstance(raw, dict) or set(raw) != {"version", "description", "kinds", "rules"}:
            _fail(source, "expected keys version, description, kinds, rules")
        kinds = raw["kinds"]
        if not isinstance(kinds, list) or "unknown" not in kinds:
            _fail(source, "kinds must be a list that includes 'unknown'")
        self.kinds = tuple(kinds)
        self.raw = raw
        exact, prefix, contains = {}, [], []
        for index, rule in enumerate(raw["rules"]):
            where = "{} rule #{}".format(source, index + 1)
            if not isinstance(rule, dict) or set(rule) != {"match", "pattern", "counterparty", "kind"}:
                _fail(where, "expected keys match, pattern, counterparty, kind")
            if rule["match"] not in _MATCHES:
                _fail(where, "match must be one of {}".format(", ".join(_MATCHES)))
            pattern = rule["pattern"]
            if not isinstance(pattern, str) or not pattern or pattern != clean_counterparty(pattern):
                _fail(where, "pattern must be non-empty and already cleaned")
            if rule["counterparty"] is not None and not isinstance(rule["counterparty"], str):
                _fail(where, "counterparty must be a string or null")
            if rule["kind"] not in self.kinds:
                _fail(where, "unknown kind {!r}".format(rule["kind"]))
            entry = (pattern, rule["counterparty"], rule["kind"])
            if rule["match"] == "exact":
                if pattern in exact:
                    _fail(where, "duplicate exact pattern")
                exact[pattern] = entry
            elif rule["match"] == "prefix":
                prefix.append(entry)
            else:
                contains.append(entry)
        self._exact = exact
        # Longest pattern first; ties broken by the pattern text, so the
        # outcome never depends on the order rules are written in.
        self._prefix = sorted(prefix, key=lambda e: (-len(e[0]), e[0]))
        self._contains = sorted(contains, key=lambda e: (-len(e[0]), e[0]))
        self._cache = {}

    def normalise(self, raw):
        """Return (canonical counterparty or None, kind)."""
        if raw in self._cache:
            return self._cache[raw]
        cleaned = clean_counterparty(raw)
        if not cleaned:
            result = (None, "unknown")
        else:
            result = None
            hit = self._exact.get(cleaned)
            if hit is None:
                for entry in self._prefix:
                    if cleaned.startswith(entry[0]):
                        hit = entry
                        break
            if hit is None:
                for entry in self._contains:
                    if entry[0] in cleaned:
                        hit = entry
                        break
            if hit is None:
                result = (cleaned, "unknown")
            else:
                result = (hit[1] or cleaned, hit[2])
        if len(self._cache) < 100000:
            self._cache[raw] = result
        return result


class MerchantCodes(object):
    def __init__(self, raw, source="merchant_codes"):
        if not isinstance(raw, dict) or set(raw) != {"version", "description", "codes"}:
            _fail(source, "expected keys version, description, codes")
        self.raw = raw
        self.categories = {}
        for code, entry in raw["codes"].items():
            where = "{} code {}".format(source, code)
            if not _CODE_RE.match(code):
                _fail(where, "codes are four digits")
            if not isinstance(entry, dict) or set(entry) != {"category", "label"}:
                _fail(where, "expected keys category, label")
            category = entry["category"]
            if not isinstance(category, str) or not _CATEGORY_RE.match(category):
                _fail(where, "category must be a lower-case identifier")
            reason = policy.protected_reason(category)
            if reason:
                _fail(where, "category {!r} {}".format(category, reason))
            self.categories[code] = category

    def category(self, code):
        return self.categories.get((code or "").strip())


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)

"""Fairness and data-minimisation policy, fixed in code.

The taxonomy file cannot switch these rules off: they live here, not in
taxonomy/tags.json, so editing the rules cannot weaken the guard.

* Protected traits are never used: no field, filter, category or tag may
  refer to religion, ethnicity, race, caste, national origin, gender, sex,
  sexual orientation, disability, health, pregnancy, family or marital
  status, or political opinion.
* Age is excluded by default. There is no age metric at all; adding one
  needs a tag explicitly marked "bank policy decides" and an engine change.
* Spending categories that act as proxies for those traits (health, charity
  and worship, childcare and school fees, pensions) cannot be used to
  include transactions in a rule.
* No rule may select a specific country or currency: that is a proxy for
  national origin, and for a remittance it is the corridor. Rules may only
  ask "abroad or not" and "foreign currency or not", or count distinct
  countries.
* Restricted categories (the proxies above, and any category whose name
  refers to a protected trait or to age) are collapsed into one opaque
  "restricted" category the moment a transaction is read, so the profile
  store never holds them. No rule may select "restricted".
* Counterparties of kind "person" are pseudonymised when read: the store
  keeps a stable token, never the person's name.
* The engine reads only the columns listed here. Any other column in the
  input files, including a protected-trait column, is never loaded.
* A customer who objected to profiling (profiling_opt_out) is excluded
  completely: never tagged, and nothing about them is kept but the id and
  the date of the objection.
"""

import re

PROTECTED_TOKENS = frozenset(
    {
        "religion", "religious", "faith", "ethnicity", "ethnic", "race",
        "racial", "caste", "nationality", "citizenship", "citizen",
        "immigrant", "immigration", "migrant", "gender", "sex", "sexual",
        "sexuality", "lgbt", "lgbtq", "disability", "disabled", "health",
        "illness", "sick", "sickness", "diagnosis", "marital", "married",
        "divorce", "divorced", "widow", "widowed", "spouse", "pregnancy",
        "pregnant", "maternity", "paternity", "child", "children", "kids",
        "family", "political", "politics",
    }
)

# Multi-word traits whose single words are too common to refuse alone.
PROTECTED_PHRASES = (
    ("national", "origin"),
    ("sexual", "orientation"),
    ("trade", "union"),
    ("country", "of", "birth"),
)

AGE_TOKENS = frozenset(
    {"age", "birth", "birthday", "dob", "born", "retired", "retirement", "senior", "elderly", "minor"}
)

PROXY_CATEGORIES = frozenset(
    {
        "healthcare", "medical", "pharmacy", "hospital", "clinic",
        "charity", "donation", "worship", "zakat", "tithe",
        "childcare", "school_fees", "education_fees",
        "pension", "disability_benefit", "maternity",
    }
)

RESTRICTED_CATEGORY = "restricted"

# Columns the engine reads. Everything else is ignored on load.
CUSTOMER_COLUMNS = (
    "customer_id",
    "account_open_date",
    "home_country",
    "home_currency",
    "profiling_opt_out",
)

# Values of profiling_opt_out that mean "not opted out". Every other non-empty
# value is an opt-out: when in doubt, the plugin stops profiling.
NOT_OPTED_OUT = frozenset({"", "false", "no", "n", "0"})

TRANSACTION_COLUMNS = (
    "txn_id",
    "customer_id",
    "posted_date",
    "amount",
    "currency",
    "direction",
    "channel",
    "category",
    "counterparty",
    "txn_country",
    "mcc",
    "balance_after",
)

# Transaction fields a rule filter may test.
FILTER_FIELDS = frozenset(
    {
        "direction",
        "category",
        "channel",
        "counterparty",
        "counterparty_kind",
        "is_foreign_currency",
        "is_foreign_country",
    }
)

BOOLEAN_FILTER_FIELDS = frozenset({"is_foreign_currency", "is_foreign_country"})

# Fields a filter may never select specific values of (national origin, corridor).
VALUE_SELECTION_REFUSED = {
    "txn_country": "selects a specific country, a proxy for national origin; use is_foreign_country",
    "currency": "selects a specific currency, a proxy for national origin or a remittance corridor; "
                "use is_foreign_currency",
    "counterparty_country": "selects the counterparty's country (a remittance corridor); never allowed",
}

# Transaction fields a "distinct" metric may count. Counting countries says
# how many, never which.
DISTINCT_FIELDS = frozenset({"counterparty", "txn_country"})

_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")


def _tokens(name):
    return [t for t in _TOKEN_SPLIT.split(str(name).lower()) if t]


def protected_reason(name):
    """Return why a field, category or tag name is refused, or None if allowed."""
    tokens = _tokens(name)
    for token in tokens:
        if token in PROTECTED_TOKENS:
            return "refers to a protected trait ({!r}); tags never use protected traits".format(token)
    for phrase in PROTECTED_PHRASES:
        size = len(phrase)
        for start in range(len(tokens) - size + 1):
            if tuple(tokens[start:start + size]) == phrase:
                return "refers to a protected trait ({!r}); tags never use protected traits".format(" ".join(phrase))
    for token in tokens:
        if token in AGE_TOKENS:
            return (
                "refers to age ({!r}); age is excluded by default and needs a tag "
                "marked 'bank policy decides' plus an engine change".format(token)
            )
    return None


def proxy_category_reason(category):
    """Return why a category may not be used to include transactions, or None."""
    reason = protected_reason(category)
    if reason:
        return reason
    if str(category).lower() in PROXY_CATEGORIES:
        return "is a proxy for a protected trait or for age; it cannot select transactions"
    if str(category).lower() == RESTRICTED_CATEGORY:
        return "is the restricted category that proxies are collapsed into; it cannot select transactions"
    return None


def stored_category(category):
    """The category as the engine keeps it: restricted categories collapse into one."""
    if category and (category in PROXY_CATEGORIES or protected_reason(category)):
        return RESTRICTED_CATEGORY
    return category


def opted_out(value):
    """Does a profiling_opt_out value mean the customer objected? Anything but
    an empty or clearly negative value does."""
    return str(value or "").strip().lower() not in NOT_OPTED_OUT

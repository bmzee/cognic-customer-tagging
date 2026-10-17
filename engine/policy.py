"""Fairness and data-minimisation policy, fixed in code.

The taxonomy file cannot switch these rules off: they live here, not in
taxonomy/tags.json, so editing the rules cannot weaken the guard.

* Protected traits are never used: no field, filter or category may refer to
  religion, ethnicity, race, caste, gender, sex, disability, marital status or
  pregnancy.
* Age is excluded by default. Stage 1 has no age metric at all; adding one
  needs a tag explicitly marked "bank policy decides" and an engine change.
* Spending categories that act as proxies for those traits (health, charity
  and worship, childcare and school fees, pensions) cannot be used to
  include transactions in a rule.
* The engine reads only the columns listed here. Any other column in the
  input files, including a protected-trait column, is never loaded.
"""

import re

PROTECTED_TOKENS = frozenset(
    {
        "religion", "religious", "faith", "ethnicity", "ethnic", "race",
        "racial", "caste", "gender", "sex", "disability", "disabled",
        "marital", "married", "pregnancy", "pregnant",
    }
)

AGE_TOKENS = frozenset({"age", "birth", "birthday", "dob", "born"})

PROXY_CATEGORIES = frozenset(
    {
        "healthcare", "medical", "pharmacy", "hospital", "clinic",
        "charity", "donation", "worship", "zakat", "tithe",
        "childcare", "school_fees", "education_fees",
        "pension", "disability_benefit", "maternity",
    }
)

# Columns the engine reads. Everything else is ignored on load.
CUSTOMER_COLUMNS = (
    "customer_id",
    "account_open_date",
    "home_country",
    "home_currency",
)

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
)

# Transaction fields a rule filter may test.
FILTER_FIELDS = frozenset(
    {
        "direction",
        "category",
        "channel",
        "currency",
        "counterparty",
        "txn_country",
        "is_foreign_currency",
        "is_foreign_country",
    }
)

BOOLEAN_FILTER_FIELDS = frozenset({"is_foreign_currency", "is_foreign_country"})

# Transaction fields a "distinct" metric may count.
DISTINCT_FIELDS = frozenset({"counterparty", "txn_country", "currency"})

_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")


def _tokens(name):
    return [t for t in _TOKEN_SPLIT.split(str(name).lower()) if t]


def protected_reason(name):
    """Return why a field or category name is refused, or None if allowed."""
    tokens = _tokens(name)
    for token in tokens:
        if token in PROTECTED_TOKENS:
            return "refers to a protected trait ({!r}); tags never use protected traits".format(token)
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
    return None

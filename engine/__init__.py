"""Deterministic, explainable customer-tagging rules engine.

Reads customers.csv and transactions.csv, applies the declarative rules in
taxonomy/tags.json and returns, for each customer, the tags whose rules were
met, each with its rule, the evidence that produced it and its lifecycle
(when it entered, checked at month ends).

Standard library only. No network access, no randomness and no wall-clock
time: the result depends only on the input files, the taxonomy and the
as-of date. The engine never modifies its inputs.
"""

import os
from collections import OrderedDict

ENGINE_VERSION = "2.0.0"

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TAXONOMY = os.path.join(os.path.dirname(PACKAGE_DIR), "taxonomy", "tags.json")

from . import aggregate  # noqa: E402
from . import lifecycle as lifecycle_module  # noqa: E402
from .data import DataError, load_customers, load_transactions  # noqa: E402
from .evaluate import evaluate_customer, evaluate_data  # noqa: E402
from .taxonomy import TaxonomyError, load_taxonomy, load_taxonomy_data  # noqa: E402


class Run(object):
    """The result of one engine run: per-customer tag results plus notes."""

    def __init__(self, taxonomy, customers, as_of, results, customer_notes, run_notes, per_customer_notes,
                 lifecycles=None):
        self.taxonomy = taxonomy
        self.customers = customers
        self.as_of = as_of
        self.results = results
        self.customer_notes = customer_notes
        self.run_notes = run_notes
        self.per_customer_notes = per_customer_notes
        self.lifecycles = lifecycles or {}

    def tags_for(self, customer_id):
        return [tag_id for tag_id, r in self.results[customer_id].items() if r.state is True]


def customer_data(taxonomy, customer, txns):
    return aggregate.CustomerData.from_rows(customer, txns, taxonomy.specs)


def run(customers_path, transactions_path, taxonomy=None, as_of=None, lifecycle=True, evidence="all"):
    """Tag every customer. taxonomy may be a path, a loaded Taxonomy or None (default file).

    evidence="all" explains every tag (needed for "not met" output and --why);
    evidence="held" explains only the tags that hold, which is faster."""
    if taxonomy is None or isinstance(taxonomy, str):
        taxonomy = load_taxonomy(taxonomy or DEFAULT_TAXONOMY)
    customers, customer_notes = load_customers(customers_path, taxonomy.base_currency)
    txns, as_of, run_notes, per_customer = load_transactions(transactions_path, customers, taxonomy, as_of)
    results = OrderedDict()
    lifecycles = OrderedDict()
    for cid in customers:
        data = customer_data(taxonomy, customers[cid], txns[cid])
        current = evaluate_data(taxonomy, data, as_of, True if evidence == "all" else "held")
        results[cid] = current
        if lifecycle:
            states = lifecycle_module.checkpoint_states(taxonomy, data, as_of, taxonomy.lifecycle_months, current)
            lifecycles[cid] = lifecycle_module.lifecycle(states, current)
    return Run(taxonomy, customers, as_of, results, customer_notes, run_notes, per_customer, lifecycles)


__all__ = [
    "DEFAULT_TAXONOMY", "ENGINE_VERSION", "DataError", "Run", "TaxonomyError", "customer_data",
    "evaluate_customer", "evaluate_data", "load_customers", "load_taxonomy", "load_taxonomy_data",
    "load_transactions", "run",
]

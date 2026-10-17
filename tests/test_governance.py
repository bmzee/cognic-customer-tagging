"""The governance templates: all present, each marked for the bank's
compliance team, jurisdiction-neutral, and in step with the code."""

import os
import re
import unittest

from engine import policy
from engine.incremental import CUSTOMER_TABLES, STATE_TABLES
from tests.helpers import ROOT

FOLDER = os.path.join(ROOT, "docs", "governance")
TEMPLATES = ("README.md", "dpia.md", "customer-rights.md", "retention.md", "audit-trail.md",
             "taxonomy-change-control.md")
# Named laws, regulators and places: the templates leave all of that to the bank.
NAMED = re.compile(r"\b(GDPR|EU|EEA|UK|US|USA|FCA|CFPB|ECOA|EDPB|ICO|Article \d+|AI Act|Regulation [A-Z]|"
                   r"Europe(an)?|America(n)?|Britain|British)\b")


def read(name):
    with open(os.path.join(FOLDER, name), encoding="utf-8") as handle:
        return handle.read()


class Templates(unittest.TestCase):
    def test_every_template_is_present_and_marked_for_compliance(self):
        self.assertEqual(sorted(os.listdir(FOLDER)), sorted(TEMPLATES))
        for name in TEMPLATES:
            with self.subTest(template=name):
                self.assertIn("To be completed by the bank's compliance team", read(name))

    def test_no_law_regulator_or_place_is_named(self):
        for name in TEMPLATES:
            with self.subTest(template=name):
                match = NAMED.search(read(name))
                self.assertIsNone(match, match and match.group(0))

    def test_the_index_links_every_template(self):
        index = read("README.md")
        for name in TEMPLATES[1:]:
            self.assertIn("({})".format(name), index)

    def test_the_rights_template_matches_the_opt_out_the_builder_honours(self):
        text = read("customer-rights.md")
        self.assertIn("`profiling_opt_out`", text)
        self.assertIn("profiling_opt_out", policy.CUSTOMER_COLUMNS)
        for value in ("`true`", "`yes`", "`y`", "`1`"):
            self.assertIn(value, text)
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "tests", "test_opt_out.py")))
        self.assertIn("opt_outs", STATE_TABLES)

    def test_the_retention_and_audit_templates_name_the_store_tables(self):
        retention, audit = read("retention.md"), read("audit-trail.md")
        for table in ("ledger", "feature_buckets", "tag_state", "late_events", "opt_outs", "runs", "run_tags"):
            self.assertIn("`{}`".format(table), retention + audit, table)
        for table in CUSTOMER_TABLES:
            self.assertIn("`{}`".format(table), retention + audit, table)

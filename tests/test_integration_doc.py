"""docs/INTEGRATION.md: it covers what the plan asks for, every open
question it links exists, and every file it points to is there."""

import json
import os
import re
import unittest

from tests.helpers import ROOT

DOCS = os.path.join(ROOT, "docs")


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class IntegrationGuide(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = read(os.path.join(DOCS, "INTEGRATION.md"))

    def test_it_covers_each_item_the_plan_names(self):
        for heading in ("## 1. The safety file entries", "## 2. The server image", "## 3. The read-only data copy",
                        "## 4. Running the builder", "## 5. What an administrator approves"):
            self.assertIn(heading, self.text)
        self.assertIn("watchers and standing goals", self.text)

    def test_every_linked_open_question_exists(self):
        questions = set(re.findall(r"^\| (Q\d+) \|", read(os.path.join(DOCS, "OPEN-QUESTIONS.md")), re.M))
        linked = set(re.findall(r"\[(Q\d+)\]\(OPEN-QUESTIONS\.md\)", self.text))
        self.assertGreater(len(linked), 25)
        self.assertEqual(sorted(linked - questions), [])

    def test_every_relative_link_and_named_file_exists(self):
        for target in re.findall(r"\]\(([^)#:]+)\)", self.text):
            self.assertTrue(os.path.exists(os.path.join(DOCS, target)), target)
        for path in re.findall(r"`((?:skills|commands|agents|server|engine|tools|evals|docs|bin|\.github)/[^`\s]*)`",
                               self.text):
            self.assertTrue(os.path.exists(os.path.join(ROOT, path.rstrip("/"))), path)

    def test_the_safety_file_facts_it_states_are_true(self):
        safety = json.loads(read(os.path.join(ROOT, "cognic.plugin.json")))
        self.assertEqual(safety["scope"]["roles"], ["employee"])
        self.assertEqual(safety["effects"], ["read"])
        self.assertEqual(safety["dataClasses"], ["confidential", "sensitive"])
        self.assertEqual(safety["servers"][0]["network"]["mode"], "deny")
        self.assertEqual(len(safety["tools"]), 6)
        self.assertTrue(all(t["effect"] == "read" and t["tier"] == "reader" for t in safety["tools"]))
        self.assertIn("`{}`".format(safety["schemaVersion"]), self.text)

"""The evaluation scenarios: well formed, every expected call valid, and every
fact an answer must contain actually present in what the reader returns for
the synthetic fixture store. Refusals expect no calls and name one of the
four rules every instruction file states."""

import json
import os
import shutil
import tempfile
import unittest
from collections import Counter

from engine import build
from server import schema, tools
from server.tools import Reader
from tests.helpers import ROOT, TAXONOMY

DATA = os.path.join(ROOT, "data")
# Fields that quote the governance text and tag limitations: they name the
# prohibited uses on purpose, so "must not say" is checked everywhere else.
QUOTED = ("intended_use", "prohibited_uses", "limitations")


def load():
    with open(os.path.join(ROOT, "evals", "scenarios.json"), encoding="utf-8") as handle:
        return json.load(handle)


def strings(value, skip=QUOTED):
    """Every string and number in a result, outside the quoted governance fields."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key not in skip:
                for text in strings(item, skip):
                    yield text
    elif isinstance(value, list):
        for item in value:
            for text in strings(item, skip):
                yield text
    elif isinstance(value, (str, int, float)) and not isinstance(value, bool):
        yield str(value)


def objects(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            for found in objects(item):
                yield found
    elif isinstance(value, list):
        for item in value:
            for found in objects(item):
                yield found


def contains(results, fact):
    if isinstance(fact, dict):
        return any(all(k in o and o[k] == v for k, v in fact.items()) for r in results for o in objects(r))
    return any(fact in text for r in results for text in strings(r, skip=()))


class Format(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = load()
        cls.scenarios = cls.doc["scenarios"]

    def test_header_and_size(self):
        self.assertEqual(self.doc["format"], "customer-tagging.evals/1")
        self.assertGreaterEqual(len(self.scenarios), 40)
        ids = [s["id"] for s in self.scenarios]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_scenario_has_the_documented_fields(self):
        keys = {"id", "kind", "skill", "question", "expected_calls", "must_contain", "must_not_say", "refusal"}
        skills = set(os.listdir(os.path.join(ROOT, "skills")))
        commands = {"/" + f[:-3] for f in os.listdir(os.path.join(ROOT, "commands"))}
        for s in self.scenarios:
            with self.subTest(scenario=s["id"]):
                self.assertTrue(keys <= set(s), keys - set(s))
                self.assertTrue(set(s) <= keys | {"command"})
                self.assertIn(s["skill"], skills)
                if "command" in s:
                    self.assertIn(s["command"], commands)
                self.assertTrue(s["question"].strip())

    def test_kinds_and_refusals_are_covered(self):
        kinds = Counter(s["kind"] for s in self.scenarios)
        for kind in ("explain", "why-not", "segment", "meaning", "review", "history", "refusal"):
            self.assertIn(kind, kinds)
        rules = Counter(s["refusal"]["rule"] for s in self.scenarios if s["refusal"])
        self.assertEqual(set(rules), set(self.doc["rules"]))
        self.assertGreaterEqual(kinds["refusal"], 10)

    def test_refusals_call_nothing_and_name_a_rule_every_instruction_states(self):
        for s in self.scenarios:
            with self.subTest(scenario=s["id"]):
                if s["kind"] == "refusal":
                    self.assertEqual(s["expected_calls"], [])
                    self.assertEqual(s["must_contain"], [])
                    self.assertTrue(s["refusal"]["offer"])
                    rule = self.doc["rules"][s["refusal"]["rule"]]
                    with open(os.path.join(ROOT, "skills", s["skill"], "SKILL.md"), encoding="utf-8") as handle:
                        self.assertIn(rule, handle.read())
                else:
                    self.assertIsNone(s["refusal"])
                    self.assertTrue(s["expected_calls"])
                    self.assertTrue(s["must_contain"])

    def test_expected_calls_are_valid_tool_calls(self):
        listed = {t["name"]: t for t in tools.tool_list()}
        for s in self.scenarios:
            for c in s["expected_calls"]:
                with self.subTest(scenario=s["id"], tool=c["tool"]):
                    self.assertIn(c["tool"], listed)
                    self.assertIsNone(schema.check(listed[c["tool"]]["inputSchema"], c["arguments"]))


class Grounded(unittest.TestCase):
    """Every fact is in the reader's results for the fixture store, and nothing
    an answer must not say is in them (outside the quoted governance text)."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="tagging-evals-")
        cls.store = os.path.join(cls.dir, "profile.db")
        build.rebuild(os.path.join(DATA, "customers.csv"), os.path.join(DATA, "transactions.csv"), cls.store, TAXONOMY)
        cls.reader = Reader(cls.store, TAXONOMY)
        cls.doc = load()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_facts_are_in_the_results_and_forbidden_words_are_not(self):
        listed = {t["name"]: t for t in tools.tool_list()}
        for s in self.doc["scenarios"]:
            if s["refusal"]:
                continue
            with self.subTest(scenario=s["id"]):
                results = []
                for c in s["expected_calls"]:
                    result = self.reader.call(c["tool"], c["arguments"])
                    self.assertIsNone(schema.check(listed[c["tool"]]["outputSchema"], result))
                    results.append(result)
                for fact in s["must_contain"]:
                    self.assertTrue(contains(results, fact), fact)
                texts = [t.lower() for r in results for t in strings(r)]
                for phrase in s["must_not_say"]:
                    self.assertFalse(any(phrase.lower() in t for t in texts), phrase)


if __name__ == "__main__":
    unittest.main()

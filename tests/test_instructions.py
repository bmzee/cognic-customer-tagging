"""Skills, commands and the agent: instructions only, each with the four
rules, within Cognic's limits, and matching their safety-file entries."""

import json
import os
import re
import unittest

from server import schema, tools
from tests.helpers import ROOT

ALWAYS = (
    "- Never change data.",
    "- Never infer or discuss protected traits:",
    "- Refuse requests to tag, sort, rank or select people by a protected trait",
    "- Refuse credit, pricing, fraud or AML decisions",
)
EXPANSIONS = (r"\$ARGUMENTS", r"\$\d", r"!`", r"(^|\s)@[\w./-]", r"\$\{")


def frontmatter(path):
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not match:
        raise AssertionError("{} has no frontmatter".format(path))
    fields = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip().strip('"')
    return fields, match.group(2), text


def instruction_files():
    files = [os.path.join("skills", d, "SKILL.md") for d in sorted(os.listdir(os.path.join(ROOT, "skills")))]
    files += [os.path.join("commands", f) for f in sorted(os.listdir(os.path.join(ROOT, "commands")))]
    files += [os.path.join("agents", f) for f in sorted(os.listdir(os.path.join(ROOT, "agents")))]
    return files


class EveryInstructionFile(unittest.TestCase):
    def test_states_the_four_rules(self):
        for path in instruction_files():
            _, body, _ = frontmatter(os.path.join(ROOT, path))
            with self.subTest(file=path):
                for rule in ALWAYS:
                    self.assertIn(rule, body)

    def test_has_a_description_and_no_model_or_execution_setting(self):
        for path in instruction_files():
            fields, body, text = frontmatter(os.path.join(ROOT, path))
            with self.subTest(file=path):
                self.assertTrue(fields.get("description"))
                for forbidden in ("model", "allowed-tools", "permissionMode", "hooks"):
                    self.assertNotIn(forbidden, fields)
                self.assertNotRegex(body, r"```(bash|sh|shell)\b", "instruction files never run commands")
                self.assertNotIn("--out-dir", text)

    def test_names_only_the_readers_tools(self):
        names = {t["name"] for t in tools.tool_list()}
        for path in instruction_files():
            _, body, _ = frontmatter(os.path.join(ROOT, path))
            for name in re.findall(r"^- `([a-z_]+)` \(", body, re.M) + re.findall(r"call `([a-z_]+)`", body):
                self.assertIn(name, names, (path, name))


class Commands(unittest.TestCase):
    def test_commands_are_short_and_never_expand_arguments(self):
        for name in sorted(os.listdir(os.path.join(ROOT, "commands"))):
            _, _, text = frontmatter(os.path.join(ROOT, "commands", name))
            with self.subTest(command=name):
                self.assertLess(len(text.encode("utf-8")), 4000)
                for pattern in EXPANSIONS:
                    self.assertIsNone(re.search(pattern, text), pattern)

    def test_the_three_commands_exist(self):
        self.assertEqual(sorted(os.listdir(os.path.join(ROOT, "commands"))),
                         ["explain-customer.md", "tag-customers.md", "tag-report.md"])


class Skills(unittest.TestCase):
    def test_the_three_skills_exist_and_are_named(self):
        for name in ("customer-tagging", "segment-explorer", "tag-review"):
            fields, _, _ = frontmatter(os.path.join(ROOT, "skills", name, "SKILL.md"))
            self.assertEqual(fields["name"], name)

    def test_segment_explorer_keeps_lists_minimal(self):
        _, body, _ = frontmatter(os.path.join(ROOT, "skills", "segment-explorer", "SKILL.md"))
        for phrase in ("ids and display names only", "one page at a time", "never for sales targeting"):
            self.assertIn(phrase, body)


class Agent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fields, cls.body, cls.text = frontmatter(os.path.join(ROOT, "agents", "customer-profiler.md"))
        with open(os.path.join(ROOT, "cognic.plugin.json"), encoding="utf-8") as handle:
            cls.entry = json.load(handle)["agents"][0]

    def test_a_finite_list_of_the_readers_tools(self):
        listed = [t.strip() for t in self.fields["tools"].split(",")]
        self.assertNotIn("*", self.fields["tools"])
        prefix = "mcp__plugin_customer-tagging_profiles__"
        self.assertTrue(all(t.startswith(prefix) for t in listed), listed)
        self.assertEqual(sorted(t[len(prefix):] for t in listed), sorted(self.entry["tools"]))
        self.assertEqual(sorted(self.entry["tools"]), sorted(t["name"] for t in tools.tool_list()))

    def test_the_output_schema_is_explicit_and_matches_the_safety_file(self):
        block = json.loads(re.search(r"```json\n(.*?)\n```", self.body, re.S).group(1))
        self.assertEqual(block, self.entry["outputSchema"])
        schema.check_schema(block)
        self.assertEqual(self.entry["tier"], "reader")

    def test_a_refusal_fits_the_schema(self):
        refusal = {"customer_id": "C0001", "as_of": "2026-09-30", "status": "refused",
                   "summary": "This request asks for a credit decision, which tags must never be used for.",
                   "tags": [], "refusal_reason": "Refuse credit, pricing, fraud or AML decisions"}
        self.assertIsNone(schema.check(self.entry["outputSchema"], refusal))
        self.assertIsNotNone(schema.check(self.entry["outputSchema"], dict(refusal, score=0.9)))


if __name__ == "__main__":
    unittest.main()

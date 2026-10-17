"""cognic.plugin.json: consistent with the plugin, read-only, and valid against the draft schema.

The draft schema is not part of this public repository. Set COGNIC_SAFETY_SCHEMA
to its path to run the full schema validation; otherwise that one test is skipped.
"""

import json
import os
import re
import sys
import unittest

from tests.helpers import ROOT

sys.path.insert(0, os.path.join(ROOT, "tools"))
from validate_safety_file import Validator, load_json  # noqa: E402

# Modules of the builder, which writes the profile store, and of the card
# generator: not part of the read-only skill.
WRITING_MODULES = {"build.py", "cards.py", "events.py", "feeds.py", "incremental.py", "profile.py", "store.py"}


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


class SafetyFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.safety = load_json(os.path.join(ROOT, "cognic.plugin.json"))
        with open(os.path.join(ROOT, ".claude-plugin", "plugin.json"), encoding="utf-8") as handle:
            cls.manifest = json.load(handle)

    def test_identity_matches_the_plugin_manifest(self):
        self.assertEqual(self.safety["pluginId"], self.manifest["name"])
        self.assertEqual(self.safety["pluginVersion"], self.manifest["version"])
        self.assertEqual(set(self.manifest), {"name", "version", "description", "author"})

    def test_declares_read_only_and_confidential_personal_data(self):
        self.assertEqual(self.safety["effects"], ["read"])
        self.assertEqual(self.safety["consentClass"], "none")
        self.assertEqual(self.safety["dataClasses"], ["confidential", "sensitive"])
        for key in ("hooks", "dependencies"):
            self.assertEqual(self.safety[key], [], key)
        # The one server is the read-only reader; every tool reads and nothing else.
        self.assertEqual([s["id"] for s in self.safety["servers"]], ["profiles"])
        for tool in self.safety["tools"]:
            self.assertEqual((tool["effect"], tool["tier"], tool["enforcement"]), ("read", "reader", "read-only"))

    def test_every_component_is_declared_and_exists(self):
        skills = sorted(d for d in os.listdir(os.path.join(ROOT, "skills")) if not d.startswith("."))
        commands = sorted(f[:-3] for f in os.listdir(os.path.join(ROOT, "commands")) if f.endswith(".md"))
        self.assertEqual(sorted(s["id"] for s in self.safety["skills"]), skills)
        self.assertEqual(sorted(c["id"] for c in self.safety["commands"]), commands)
        # The read-only skill runs the print-only engine. The modules that write
        # (the store builder, and the card generator) are not part of it.
        engine_files = sorted("engine/" + f for f in os.listdir(os.path.join(ROOT, "engine"))
                              if f.endswith(".py") and f not in WRITING_MODULES)
        skill = self.safety["skills"][0]
        self.assertEqual(skill["scripts"], engine_files)
        for name in WRITING_MODULES:
            self.assertNotIn("engine/" + name, skill["scripts"])
        self.assertIn("taxonomy/tags.json", skill["resources"])
        for component in self.safety["skills"] + self.safety["commands"]:
            for path in [component["path"]] + component["resources"] + component["scripts"]:
                self.assertTrue(os.path.isfile(os.path.join(ROOT, path)), path)
            for key in ("roles", "agents"):
                self.assertTrue(set(component["scope"][key]) <= set(self.safety["scope"][key]))
            self.assertEqual(component["profile"], "workbench")
            self.assertEqual(component["tier"], "instruction")

    def test_skill_and_command_files(self):
        fields, body, _ = frontmatter(os.path.join(ROOT, "skills", "customer-tagging", "SKILL.md"))
        self.assertEqual(fields["name"], "customer-tagging")
        self.assertTrue(fields["description"])
        self.assertIn("Never pass `--out-dir`", body)
        fields, body, text = frontmatter(os.path.join(ROOT, "commands", "tag-customers.md"))
        self.assertTrue(fields["description"])
        self.assertLess(len(text.encode("utf-8")), 4000)
        for forbidden in (r"\$ARGUMENTS", r"\$\d", r"!`", r"(^|\s)@[\w./-]", r"\$\{"):
            self.assertIsNone(re.search(forbidden, text), forbidden)

    def test_valid_against_the_draft_schema(self):
        path = os.environ.get("COGNIC_SAFETY_SCHEMA")
        if not path:
            self.skipTest("draft schema not in this repository; set COGNIC_SAFETY_SCHEMA to its path")
        errors = Validator(load_json(path)).errors(self.safety)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()

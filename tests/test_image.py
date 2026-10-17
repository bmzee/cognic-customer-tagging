"""The image definition, checked without building it (images are built in
CI only), and the smoke test run against a local reader process."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from engine import build
from tests.helpers import ROOT, TAXONOMY


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
        return handle.read()


class Containerfile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = read("Containerfile")
        cls.instructions = [line.strip() for line in cls.text.splitlines()
                            if line.strip() and not line.strip().startswith("#")]
        with open(os.path.join(ROOT, "cognic.plugin.json"), encoding="utf-8") as handle:
            cls.server = json.load(handle)["servers"][0]

    def test_the_base_image_is_pinned_by_digest(self):
        base = re.search(r"^ARG BASE=(\S+)$", self.text, re.M).group(1)
        self.assertRegex(base, r"^python:[0-9.]+-slim@sha256:[0-9a-f]{64}$")
        froms = [line for line in self.instructions if line.startswith("FROM ")]
        self.assertTrue(all(line.startswith("FROM ${BASE}") for line in froms), froms)

    def test_nothing_is_installed_and_the_user_is_not_root(self):
        for line in self.instructions:
            self.assertNotRegex(line, r"\b(apt|apt-get|apk|yum|dnf|pip|pip3|curl|wget)\b", line)
        users = [line for line in self.instructions if line.startswith("USER ")]
        self.assertEqual(users, ["USER 10001:10001"])

    def test_the_entrypoint_is_the_command_the_safety_file_pins(self):
        entrypoint = json.loads(re.search(r"^ENTRYPOINT (\[.*\])$", self.text, re.M).group(1))
        command = json.loads(re.search(r"^CMD (\[.*\])$", self.text, re.M).group(1))
        self.assertEqual(entrypoint, [self.server["command"]])
        self.assertEqual(command, self.server["args"])

    def test_only_code_taxonomy_and_the_fixture_store_go_in(self):
        sources = []
        for line in self.instructions:
            if line.startswith("COPY ") and "--from=" not in line:
                parts = [p for p in line.split()[1:] if not p.startswith("--")]
                sources.extend(parts[:-1])
        for source in sources:
            self.assertTrue(os.path.exists(os.path.join(ROOT, source)), source)
            self.assertFalse(source.startswith(("tests", "docs", ".git", "cognic.plugin.json")), source)
        ignore = read(".dockerignore")
        self.assertIn("\n*\n", "\n" + ignore)

    def test_the_safety_file_image_is_a_digest_reference(self):
        self.assertRegex(self.server["image"], r"^[a-z0-9][a-z0-9./:_-]*@sha256:[0-9a-f]{64}$")


class SmokeLocally(unittest.TestCase):
    def test_the_smoke_test_passes_against_a_local_reader(self):
        folder = tempfile.mkdtemp(prefix="tagging-smoke-")
        try:
            store = os.path.join(folder, "profile.db")
            data = os.path.join(ROOT, "data")
            build.rebuild(os.path.join(data, "customers.csv"), os.path.join(data, "transactions.csv"), store, TAXONOMY)
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
            result = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "smoke.py"), "--", sys.executable,
                                     os.path.join(ROOT, "bin", "profile-reader"), "--store", store],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
                                    env=env, timeout=300)
            summary = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertEqual(summary["problems"], [], result.stderr)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(summary["tools"], 6)
        finally:
            shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

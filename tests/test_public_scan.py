"""A last scan of every tracked file for things a public repository must not
hold: e-mail addresses, private hosts and addresses, keys and tokens.
Generic patterns only; model names are checked in test_cli."""

import os
import re
import subprocess
import unittest

from tests.helpers import ROOT

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Placeholders and addresses that are fine in public: none of them reach anyone.
EMAIL_ALLOWED = re.compile(r"@(example\.(com|org|net)|users\.noreply\.github\.com)$")
PRIVATE_HOST = re.compile(r"\b[a-z0-9-]+(\.[a-z0-9-]+)*\.(internal|intranet|corp|lan|local|localdomain)\b", re.I)
PRIVATE_IP = re.compile(r"\b(10\.\d{1,3}|192\.168|172\.(1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b")
# Token prefixes are split so that secret scanners do not flag this file itself.
SECRETS = re.compile("|".join([
    r"-----BEGIN [A-Z ]*PRIVATE " + r"KEY-----",
    r"\b" + "AK" + r"IA[0-9A-Z]{16}\b",
    r"\b" + "g" + r"h[pousr]_[A-Za-z0-9]{30,}\b",
    r"\b" + "github" + r"_pat_[A-Za-z0-9_]{20,}\b",
    r"\b" + "xo" + r"x[abprs]-[A-Za-z0-9-]{10,}\b",
    r"\b" + "s" + r"k-[A-Za-z0-9]{20,}\b",
    r"\b" + "AI" + r"za[0-9A-Za-z_-]{35}\b",
    r"(password|passwd|secret|api[_-]?key|token)\s*[:=]\s*['\"][^'\"]{6,}['\"]",
]), re.I)


def tracked_files():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


class PublicScan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.files = tracked_files()
        except (OSError, subprocess.CalledProcessError):
            raise unittest.SkipTest("not a git checkout")
        cls.texts = {}
        for path in cls.files:
            try:
                with open(os.path.join(ROOT, path), encoding="utf-8") as handle:
                    cls.texts[path] = handle.read()
            except (UnicodeDecodeError, OSError):
                continue

    def hits(self, pattern, allowed=None):
        found = []
        for path, text in self.texts.items():
            for match in pattern.finditer(text):
                if allowed is None or not allowed.search(match.group(0)):
                    found.append("{}: {}".format(path, match.group(0)))
        return found

    def test_no_email_addresses(self):
        self.assertEqual(self.hits(EMAIL, EMAIL_ALLOWED), [])

    def test_no_private_hosts_or_addresses(self):
        self.assertEqual(self.hits(PRIVATE_HOST), [])
        self.assertEqual(self.hits(PRIVATE_IP), [])

    def test_no_keys_or_tokens(self):
        self.assertEqual(self.hits(SECRETS), [])

    def test_every_tracked_text_file_was_scanned(self):
        self.assertGreater(len(self.texts), 100)

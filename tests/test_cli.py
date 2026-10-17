"""Command line, determinism, the print-only (read-only) mode and static guarantees."""

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from tests.helpers import ROOT, TAXONOMY

DATA = os.path.join(ROOT, "data")
ENGINE_DIR = os.path.join(ROOT, "engine")


def run_cli(args, cwd=ROOT):
    env = dict(os.environ, PYTHONPATH=ROOT, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, "-m", "engine"] + args, cwd=cwd, env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)


def inputs(folder=DATA):
    return ["--customers", os.path.join(folder, "customers.csv"),
            "--transactions", os.path.join(folder, "transactions.csv")]


def snapshot(folder):
    state = {}
    for base, dirs, files in os.walk(folder):
        for name in files:
            path = os.path.join(base, name)
            with open(path, "rb") as handle:
                state[os.path.relpath(path, folder)] = hashlib.sha256(handle.read()).hexdigest()
        for name in dirs:
            state[os.path.relpath(os.path.join(base, name), folder) + "/"] = "dir"
    return state


class Determinism(unittest.TestCase):
    def test_two_runs_write_byte_identical_files(self):
        dirs = [tempfile.mkdtemp(prefix="tagging-out-") for _ in range(2)]
        try:
            for out in dirs:
                result = run_cli(inputs() + ["--out-dir", out])
                self.assertEqual(result.returncode, 0, result.stderr)
            for name in ("tagged.json", "tagged.csv"):
                with open(os.path.join(dirs[0], name), "rb") as a, open(os.path.join(dirs[1], name), "rb") as b:
                    self.assertEqual(a.read(), b.read(), name)
            with open(os.path.join(dirs[0], "tagged.json"), encoding="utf-8") as handle:
                record = json.load(handle)
            self.assertEqual(record["as_of"], "2026-09-30")
            self.assertEqual(len(record["customers"]), 300)
            first = record["customers"][0]
            self.assertEqual(first["customer_id"], "C0001")
            self.assertEqual([t["id"] for t in first["tags"]], ["salary-earner", "active-customer"])
            self.assertEqual(record["taxonomy_hash"], TAXONOMY.content_hash)
            # Held at every one of the 6 month-end checks kept (lifecycle_months).
            self.assertEqual(first["tags"][0]["entered_on"], "2026-04-30")
            self.assertTrue(first["tags"][0]["since_window_start"])
            self.assertTrue(first["tags"][0]["evidence"])
            with open(os.path.join(dirs[0], "tagged.csv"), encoding="utf-8") as handle:
                header = handle.readline().strip()
            self.assertEqual(header, "as_of,customer_id,tag_id,tag_name,entered_on,reason,rule,evidence")
        finally:
            for out in dirs:
                shutil.rmtree(out, ignore_errors=True)


class ReadOnly(unittest.TestCase):
    def test_print_only_mode_writes_nothing(self):
        work = tempfile.mkdtemp(prefix="tagging-ro-")
        try:
            for name in ("customers.csv", "transactions.csv"):
                shutil.copy(os.path.join(DATA, name), work)
            before_work, before_repo = snapshot(work), snapshot(ROOT)
            for extra in ([], ["--format", "text", "--customer", "C0003"],
                          ["--customer", "C0003", "--why", "saver", "--format", "text"], ["--include-unmet"]):
                result = run_cli(inputs(work) + extra, cwd=work)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(snapshot(work), before_work)
            self.assertEqual(snapshot(ROOT), before_repo)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_out_dir_never_overwrites_an_input(self):
        work = tempfile.mkdtemp(prefix="tagging-ro-")
        try:
            shutil.copy(os.path.join(DATA, "customers.csv"), work)
            shutil.copy(os.path.join(DATA, "transactions.csv"), os.path.join(work, "tagged.csv"))
            before = snapshot(work)
            result = run_cli(["--customers", os.path.join(work, "customers.csv"),
                              "--transactions", os.path.join(work, "tagged.csv"), "--out-dir", work])
            self.assertEqual(result.returncode, 2)
            self.assertIn("refusing to overwrite", result.stderr)
            self.assertEqual(snapshot(work), before)
        finally:
            shutil.rmtree(work, ignore_errors=True)


class Commands(unittest.TestCase):
    def test_text_explanation(self):
        result = run_cli(inputs() + ["--format", "text", "--customer", "C0001"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("salary credited monthly, 6 of last 6 months", result.stdout)
        self.assertIn("Rule:", result.stdout)
        self.assertIn("Evidence:", result.stdout)

    def test_why_explains_a_tag_that_does_not_apply(self):
        result = run_cli(inputs() + ["--format", "text", "--customer", "C0002", "--why", "salary-earner"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("does not apply", result.stdout)
        self.assertIn("5 (needs at least 6) - not met", result.stdout)

    def test_json_for_one_customer(self):
        result = run_cli(inputs() + ["--customer", "C0041"])
        record = json.loads(result.stdout)
        self.assertEqual([c["customer_id"] for c in record["customers"]], ["C0041"])
        with open(os.path.join(DATA, "expected_tags.json"), encoding="utf-8") as handle:
            expected = next(e for e in json.load(handle)["customers"] if e["customer_id"] == "C0041")
        self.assertEqual(sorted(n["id"] for n in record["customers"][0]["not_evaluated"]),
                         expected["expected_not_evaluated"])
        self.assertIn("customers.home_country",
                      next(n for n in record["customers"][0]["not_evaluated"] if n["id"] == "frequent-traveller")["missing"])

    def test_list_tags(self):
        result = run_cli(["--list-tags"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Salary earner (salary-earner, income)", result.stdout)

    def test_errors_exit_with_status_2(self):
        for args, message in ((inputs() + ["--customer", "NOPE"], "unknown customer"),
                              (inputs() + ["--customer", "C0001", "--why", "nope"], "unknown tag"),
                              (inputs() + ["--as-of", "30/09/2026"], "YYYY-MM-DD"),
                              (["--customers", "missing.csv", "--transactions", "missing.csv"], "error"),
                              ([], "required")):
            result = run_cli(args)
            self.assertEqual(result.returncode, 2, args)
            self.assertIn(message, result.stderr)


class StaticGuarantees(unittest.TestCase):
    FORBIDDEN_MODULES = {"socket", "ssl", "http", "urllib", "urllib2", "requests", "ftplib", "smtplib",
                         "random", "secrets", "uuid", "time", "subprocess", "multiprocessing", "threading"}

    def _engine_sources(self):
        for name in sorted(os.listdir(ENGINE_DIR)):
            if name.endswith(".py"):
                path = os.path.join(ENGINE_DIR, name)
                with open(path, encoding="utf-8") as handle:
                    yield name, handle.read()

    # The builder records when a run started and finished in the runs table;
    # that is the only place the clock is read, and never in a calculation.
    CLOCK_ALLOWED = {"build.py": {"now"}}

    def test_engine_has_no_network_randomness_or_clock(self):
        for name, source in self._engine_sources():
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    modules = [(node.module or "").split(".")[0]]
                else:
                    continue
                for module in modules:
                    self.assertNotIn(module, self.FORBIDDEN_MODULES, "{} imports {}".format(name, module))
            clock = [node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
                     and node.attr in ("today", "now", "utcnow", "time", "monotonic", "perf_counter")
                     and node.attr not in self.CLOCK_ALLOWED.get(name, ())]
            self.assertEqual(clock, [], "{} reads the clock".format(name))

    def test_no_model_names_in_code_or_config(self):
        families = ["cl" + "aude", "op" + "us", "son" + "net", "hai" + "ku", "fa" + "ble", "myth" + "os",
                    "g" + "pt", "gem" + "ini", "lla" + "ma", "mis" + "tral"]
        pattern = re.compile(r"\b(" + "|".join(families) + r")\b", re.IGNORECASE)
        allowed = re.compile(r"\.cl" + r"aude-plugin")
        paths = []
        for folder in ("engine", "taxonomy", "skills", "commands", "tools", "tests", "docs", ".github", ".cl" + "aude-plugin"):
            for base, _, files in os.walk(os.path.join(ROOT, folder)):
                paths.extend(os.path.join(base, f) for f in files if not f.endswith(".pyc"))
        paths += [os.path.join(ROOT, "data", "generate.py"), os.path.join(ROOT, "cognic.plugin.json")]
        for path in paths:
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as handle:
                text = allowed.sub("", handle.read())
            self.assertIsNone(pattern.search(text), "model name in {}".format(os.path.relpath(path, ROOT)))


if __name__ == "__main__":
    unittest.main()

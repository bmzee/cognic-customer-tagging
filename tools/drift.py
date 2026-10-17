#!/usr/bin/env python3
"""Tag-prevalence drift, from the runs recorded in profile stores.

python3 tools/drift.py report --store profile.db [--store older.db ...] [--out drift.md] [--json]
    Read the runs that recorded prevalence (every rebuild, and every follow
    batch whose tick moved the as-of date), compare each with a frozen
    baseline, and write a Markdown report. Several stores may be given: a
    store that is rebuilt on a schedule keeps only its latest run, so keep
    the old stores (or copies) and pass them all.

python3 tools/drift.py demo --out docs/drift-report.md
    Follow the synthetic data in data/ month by month (a rebuild at the end
    of March 2026, then one batch and one month-end tick for each month to
    September) into a temporary store, and write its drift report. This is
    the committed example report.

The method, from docs/research/fairness-testing.md:

* The baseline is the mean prevalence of the first three recorded runs after
  each taxonomy change (a new content hash), then frozen.
* For each later run and tag: prevalence (customers holding the tag divided
  by customers in the store), the change in points and relative to the
  baseline, and a two-sided two-proportion z-test against the baseline.
  WARN at a 25% relative change of at least 1 point, ALERT at 50% and at
  least 2 points; both need p below 0.01. A tag whose prevalence falls to
  zero when at least five customers were expected to hold it is an ALERT.
* The population size: ALERT when it changes by 20% or more.
* The spread of tags per customer (0, 1, 2, 3, 4 or more): the population
  stability index against the baseline, empty bands counted as half a
  customer. WARN at 0.10, ALERT at 0.25, shown beside the value chance alone
  would exceed one time in a hundred (chi-square approximation).

Drift is attribute-blind: the runs hold counts only. It says a tag's
behaviour changed, not why, and it is never a fairness result.
Read-only: stores are opened with mode=ro. Standard library only.
"""

import argparse
import json
import math
import os
import shutil
import sys
import tempfile
from collections import OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine import store as store_module  # noqa: E402

BASELINE_RUNS = 3
WARN_RELATIVE, WARN_POINTS = 0.25, 1.0
ALERT_RELATIVE, ALERT_POINTS = 0.50, 2.0
SIGNIFICANCE = 0.01
POPULATION_ALERT = 0.20
ZERO_EXPECTED = 5  # a tag falling to zero alerts when at least this many customers were expected to hold it
PSI_WARN, PSI_ALERT = 0.10, 0.25
CHI2_4DF_99 = 13.2767  # 99th percentile of chi-square with 4 degrees of freedom (five bands)
BANDS = ("0", "1", "2", "3", "4+")
LEVELS = ("ok", "warn", "alert")


def p_two_sided(z):
    return math.erfc(abs(z) / math.sqrt(2.0))


def two_proportion_p(p0, n0, p1, n1):
    """Two-sided p-value of a two-proportion z-test (pooled standard error)."""
    if n0 <= 0 or n1 <= 0:
        return 1.0
    pooled = (p0 * n0 + p1 * n1) / (n0 + n1)
    se = math.sqrt(pooled * (1.0 - pooled) * (1.0 / n0 + 1.0 / n1))
    if se == 0.0:
        return 1.0 if p0 == p1 else 0.0
    return p_two_sided((p1 - p0) / se)


def psi(expected, actual):
    """Population stability index between two band-count dicts, empty bands as half a count."""
    e_total = float(sum(max(expected[b], 0.5) for b in BANDS))
    a_total = float(sum(max(actual[b], 0.5) for b in BANDS))
    value = 0.0
    for band in BANDS:
        e = max(expected[band], 0.5) / e_total
        a = max(actual[band], 0.5) / a_total
        value += (a - e) * math.log(a / e)
    return value


def read_runs(paths):
    """Every run with recorded prevalence, from every store, ordered by as-of date."""
    runs = []
    for order, path in enumerate(paths):
        connection = store_module.connect_ro(path)
        try:
            store_module.check_store(connection)
            rows = connection.execute(
                "SELECT run_id, kind, as_of, taxonomy_version, taxonomy_hash, customers FROM runs "
                "WHERE run_id IN (SELECT run_id FROM run_tags) ORDER BY run_id").fetchall()
            for run_id, kind, as_of, version, content_hash, customers in rows:
                tags = OrderedDict(
                    (tag, {"held": held, "suppressed": suppressed, "not_evaluated": not_evaluated})
                    for tag, held, suppressed, not_evaluated in connection.execute(
                        "SELECT tag_id, held, suppressed, not_evaluated FROM run_tags WHERE run_id = ? "
                        "ORDER BY tag_id", (run_id,)))
                spread = dict.fromkeys(BANDS, 0)
                spread.update(dict(connection.execute(
                    "SELECT band, customers FROM run_spread WHERE run_id = ?", (run_id,))))
                runs.append({"store": os.path.basename(path), "order": order, "run_id": run_id, "kind": kind,
                             "as_of": as_of, "taxonomy_version": version, "taxonomy_hash": content_hash,
                             "customers": customers, "tags": tags, "spread": spread})
        finally:
            connection.close()
    runs.sort(key=lambda r: (r["as_of"], r["order"], r["run_id"]))
    return runs


def _prevalence(run, tag):
    counts = run["tags"].get(tag)
    return (counts["held"] / float(run["customers"])) if counts and run["customers"] else 0.0


def analyse(runs):
    """Compare every run with the baseline of its taxonomy version. Returns a dict."""
    segments = []
    for run in runs:
        if not segments or segments[-1]["taxonomy_hash"] != run["taxonomy_hash"]:
            segments.append({"taxonomy_hash": run["taxonomy_hash"], "taxonomy_version": run["taxonomy_version"],
                             "runs": []})
        segments[-1]["runs"].append(run)
    results = []
    for segment in segments:
        base_runs = segment["runs"][:BASELINE_RUNS]
        tags = sorted(set().union(*(set(r["tags"]) for r in segment["runs"])))
        n0 = sum(r["customers"] for r in base_runs) / float(len(base_runs))
        p0 = {tag: sum(_prevalence(r, tag) for r in base_runs) / len(base_runs) for tag in tags}
        spread0 = {b: sum(r["spread"][b] for r in base_runs) for b in BANDS}
        forming = len(base_runs) < BASELINE_RUNS
        for index, run in enumerate(segment["runs"]):
            in_baseline = index < BASELINE_RUNS
            n1 = run["customers"]
            rows = []
            for tag in tags:
                p1 = _prevalence(run, tag)
                points = (p1 - p0[tag]) * 100.0
                relative = (p1 - p0[tag]) / p0[tag] if p0[tag] > 0 else (math.inf if p1 > 0 else 0.0)
                p_value = two_proportion_p(p0[tag], n0, p1, n1)
                level = "ok"
                if not in_baseline and not forming:
                    if p1 == 0 and p0[tag] * n1 >= ZERO_EXPECTED:
                        level = "alert"
                    elif p_value < SIGNIFICANCE and abs(relative) >= ALERT_RELATIVE and abs(points) >= ALERT_POINTS:
                        level = "alert"
                    elif p_value < SIGNIFICANCE and abs(relative) >= WARN_RELATIVE and abs(points) >= WARN_POINTS:
                        level = "warn"
                rows.append(OrderedDict([("tag", tag), ("baseline", p0[tag]), ("prevalence", p1), ("points", points),
                                         ("relative", relative), ("p_value", p_value), ("level", level)]))
            population_change = (n1 - n0) / n0 if n0 else 0.0
            population_level = "alert" if (not in_baseline and not forming and
                                           abs(population_change) >= POPULATION_ALERT) else "ok"
            value = psi(spread0, run["spread"])
            critical = CHI2_4DF_99 * (1.0 / max(n1, 1) + 1.0 / max(n0, 1))
            psi_level = "ok"
            if not in_baseline and not forming:
                psi_level = "alert" if value >= PSI_ALERT else ("warn" if value >= PSI_WARN else "ok")
            levels = [r["level"] for r in rows] + [population_level, psi_level]
            results.append(OrderedDict([
                ("store", run["store"]), ("run_id", run["run_id"]), ("kind", run["kind"]), ("as_of", run["as_of"]),
                ("taxonomy_version", run["taxonomy_version"]), ("taxonomy_hash", run["taxonomy_hash"]),
                ("role", "baseline" if in_baseline else "compared"), ("baseline_forming", forming),
                ("customers", n1), ("population_change", population_change), ("population_level", population_level),
                ("psi", value), ("psi_critical", critical), ("psi_level", psi_level),
                ("level", max(levels, key=LEVELS.index)), ("tags", rows)]))
    return OrderedDict([("runs", results), ("thresholds", OrderedDict([
        ("baseline_runs", BASELINE_RUNS), ("warn", [WARN_RELATIVE, WARN_POINTS]),
        ("alert", [ALERT_RELATIVE, ALERT_POINTS]), ("significance", SIGNIFICANCE),
        ("population_alert", POPULATION_ALERT), ("psi", [PSI_WARN, PSI_ALERT])]))])


def _pct(value):
    return "{:.1f}%".format(value * 100.0)


def _rel(value):
    if value == math.inf:
        return "new"
    return "{:+.0f}%".format(value * 100.0)


def _p(value):
    return "<0.0001" if value < 0.0001 else "{:.4f}".format(value)


def markdown(result, title="Tag drift report", sources=None):
    runs = result["runs"]
    out = ["# {}".format(title), ""]
    out.append("Generated by `tools/drift.py` from the prevalence the builder records with each run. "
               "Drift is attribute-blind: it shows that a tag's prevalence moved, not why, and it is never a "
               "fairness finding. A flag is a reason for the taxonomy owner to look (see the `tag-review` skill).")
    out.append("")
    if sources:
        out.append(sources)
        out.append("")
    out.append("Method: the baseline is the mean of the first {} recorded runs after each taxonomy change, then "
               "frozen. WARN at a {:.0f}% relative change of at least {:.0f} point; ALERT at {:.0f}% and at least {:.0f} "
               "points; both need a two-proportion z-test p-value below {}. A tag falling to zero when at least {} "
               "customers were expected to hold it, or the population changing by {:.0f}% or more, is an ALERT. The spread of tags per customer is compared with the "
               "population stability index (WARN {:.2f}, ALERT {:.2f}), shown beside the value chance alone would "
               "exceed one time in a hundred.".format(
                   BASELINE_RUNS, WARN_RELATIVE * 100, WARN_POINTS, ALERT_RELATIVE * 100, ALERT_POINTS, SIGNIFICANCE,
                   ZERO_EXPECTED, POPULATION_ALERT * 100, PSI_WARN, PSI_ALERT))
    out.append("")
    if not runs:
        out.append("No run has recorded prevalence yet.")
        return "\n".join(out) + "\n"
    counts = {level: sum(1 for r in runs if r["level"] == level) for level in LEVELS}
    flagged_tags = sum(1 for r in runs for t in r["tags"] if t["level"] != "ok")
    out.append("## Summary")
    out.append("")
    out.append("{} runs read; {} in a baseline. Runs: {} ok, {} warn, {} alert. Tag flags across all runs: {}.".format(
        len(runs), sum(1 for r in runs if r["role"] == "baseline"), counts["ok"], counts["warn"], counts["alert"],
        flagged_tags))
    out.append("")
    out.append("## Runs")
    out.append("")
    out.append("| As of | Run | Kind | Taxonomy | Role | Customers | Population change | Spread PSI (1% chance value) "
               "| Level |")
    out.append("| --- | ---: | --- | --- | --- | ---: | ---: | --- | --- |")
    for r in runs:
        out.append("| {} | {}:{} | {} | {} | {} | {:,} | {:+.1f}% | {:.4f} ({:.4f}) | {} |".format(
            r["as_of"], r["store"], r["run_id"], r["kind"], r["taxonomy_version"],
            r["role"] + (" (forming)" if r["baseline_forming"] else ""), r["customers"],
            r["population_change"] * 100.0, r["psi"], r["psi_critical"], r["level"].upper()))
    out.append("")
    out.append("## Flagged tags")
    out.append("")
    flagged = [(r, t) for r in runs for t in r["tags"] if t["level"] != "ok"]
    if not flagged:
        out.append("No tag crossed a threshold.")
    else:
        out.append("| As of | Tag | Baseline | Now | Change (points) | Relative | p-value | Level |")
        out.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |")
        for r, t in flagged:
            out.append("| {} | `{}` | {} | {} | {:+.1f} | {} | {} | {} |".format(
                r["as_of"], t["tag"], _pct(t["baseline"]), _pct(t["prevalence"]), t["points"], _rel(t["relative"]),
                _p(t["p_value"]), t["level"].upper()))
    out.append("")
    latest = runs[-1]
    out.append("## Every tag at the latest run ({})".format(latest["as_of"]))
    out.append("")
    out.append("| Tag | Baseline | Now | Change (points) | Relative | p-value | Level |")
    out.append("| --- | ---: | ---: | ---: | ---: | ---: | --- |")
    for t in latest["tags"]:
        out.append("| `{}` | {} | {} | {:+.1f} | {} | {} | {} |".format(
            t["tag"], _pct(t["baseline"]), _pct(t["prevalence"]), t["points"], _rel(t["relative"]),
            _p(t["p_value"]), t["level"].upper() if latest["role"] == "compared" else "baseline"))
    out.append("")
    out.append("## Limitations")
    out.append("")
    out.append("- Runs of one store describe the same customers, so they are not independent samples; the z-test "
               "treats them as if they were and is a screening aid, not a proof.")
    out.append("- A change can come from the customers (a season, a new product, a closed branch), from the data "
               "feed (a missing file, a new category code) or from the rules. The report cannot tell which.")
    out.append("- Small stores move a lot by chance; a tag held by few customers rarely reaches significance.")
    out.append("- A rebuilt store keeps only its latest run: keep earlier stores to see a trend.")
    return "\n".join(out) + "\n"


def build_demo_store(path, data_dir=None, start="2026-03-31"):
    """Follow the synthetic data month by month into a new store at path."""
    from engine import load_taxonomy, DEFAULT_TAXONOMY
    from engine import events as ev
    from engine.incremental import Follower, rebuild_from_events
    data_dir = data_dir or os.path.join(ROOT, "data")
    taxonomy = load_taxonomy(DEFAULT_TAXONOMY)
    events, rejected, notes = ev.events_from_csv(os.path.join(data_dir, "customers.csv"),
                                                 os.path.join(data_dir, "transactions.csv"), taxonomy)
    events = [e for e in events if e["type"] != "clock.tick"]
    month_ends = ["2026-03-31", "2026-04-30", "2026-05-31", "2026-06-30", "2026-07-31", "2026-08-31",
                  "2026-09-30"]
    first = [e for e in events if e["type"] != "transaction.posted" or e["time"] <= start]
    rebuild_from_events(first + [ev.make("demo-tick-" + start, "clock.tick", start)], path, taxonomy,
                        pre_rejected=rejected, notes=notes, snapshot="demo", clock=lambda: "demo")
    follower = Follower(path, taxonomy, clock=lambda: "demo")
    try:
        previous = start
        for end in month_ends[1:]:
            batch = [e for e in events if e["type"] == "transaction.posted" and previous < e["time"] <= end]
            follower.apply(batch + [ev.make("demo-tick-" + end, "clock.tick", end)], feed="demo",
                           position=end)
            previous = end
    finally:
        follower.close()
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command")
    report = sub.add_parser("report", help="report drift from one or more stores")
    report.add_argument("--store", action="append", required=True)
    report.add_argument("--out")
    report.add_argument("--json", action="store_true", help="print the analysis as JSON instead")
    demo = sub.add_parser("demo", help="follow the synthetic data month by month and report")
    demo.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if args.command == "report":
        result = analyse(read_runs(args.store))
        if args.json:
            sys.stdout.write(json.dumps(result, indent=2, default=str) + "\n")
            return 0
        text = markdown(result)
    elif args.command == "demo":
        text = demo_report()
    else:
        parser.print_help()
        return 2
    if getattr(args, "out", None):
        with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    else:
        sys.stdout.write(text)
    return 0


def demo_report():
    folder = tempfile.mkdtemp(prefix="tagging-drift-")
    try:
        path = build_demo_store(os.path.join(folder, "demo.db"))
        sources = ("Example: the 300 synthetic customers in `data/`, built into a store at the end of March 2026 "
                   "and then followed month by month to September (one batch of the month's transactions and one "
                   "month-end tick each), so the store recorded seven runs. Regenerate with "
                   "`python3 tools/drift.py demo --out docs/drift-report.md`.\n\n"
                   "The synthetic data is not a steady population: its history starts in October 2025, and its "
                   "labelled scenarios are built around the end of September 2026. Tags that need a long history "
                   "appear only from mid-2026, and patterns built for September look different earlier. The flags "
                   "below come from how the data was made, not from customers changing; that is exactly the kind of "
                   "cause the report cannot tell apart from a real change, which is why a flag asks a person to look.")
        return markdown(analyse(read_runs([path])), "Tag drift report (synthetic example)", sources)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

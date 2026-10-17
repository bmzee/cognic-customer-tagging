#!/usr/bin/env python3
"""Fairness kit: disparity and proxy checks on synthetic attributes.

Tests and reports only. Neither the engine nor the reader imports this
file, and the engine never reads the attributes: the kit writes synthetic
customers and transactions in the engine's input format, writes their
synthetic attributes to a separate attributes.csv, tags the customers with
the engine exactly as a run would, and joins tags and attributes only here.

python3 tools/fairness.py run [--chunks N] [--replicas R] [--background B] [--seed S]
                              [--out report.md] [--json result.json]
    Run the scenarios, write the report, and exit with status 1 when the
    gate fails. Each chunk is R copies of the 62 labelled scenarios plus B
    random background customers (by default 40 and 3,000: 5,480 customers),
    generated and tagged on its own, so memory does not grow with the size.

The attributes are stand-ins, never real people's data: trait_a has three
groups (a1 half, a2 three tenths, a3 a fifth), trait_b two equal groups,
trait_c four equal groups (shaped like age bands). The scenarios, from
docs/research/fairness-testing.md:

* null: attributes drawn independently of behaviour. No tag may FAIL; this
  measures false alarms.
* planted-proxy: the same customers, but the attributes now decide the
  things the engine must never use: the foreign country of transactions
  (the corridor; relabelled one-to-one for each customer, so "abroad or not"
  and the number of countries do not change), which restricted category a
  monthly payment falls in (worship, healthcare or childcare) and its payee,
  and protected columns added to the customer file. The engine's output must
  be identical to the null scenario's, and no tag may FAIL.
* canary: test-only tags whose rules read a behaviour planted to follow
  trait_b. A strong canary (about 60% against 10%) and a subtle one (50%
  against 35%) must FAIL; a near miss (45% against 40.5%) must not. This
  shows the kit can see what it is meant to see.

Per tag and attribute: each group's rate, the impact ratio (lowest rate over
highest), its 95% interval, each group against the reference group by a
z-test (Fisher's exact test when an expected cell is under 5) with a
Bonferroni correction, Cramer's V and the uncertainty coefficient. FAIL when
the ratio is under 0.8 and the adjusted p-value under 0.05 with enough
tagged customers (350 in the more-tagged group), or when V is 0.30 or more
and significant; WARN when the ratio is under 0.8 or V is 0.10 or more;
"inconclusive" below 350 tagged; "insufficient" under 30 members or 5
tagged. Every tag is gated, whatever its polarity. Standard library only.
"""

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
from collections import Counter, OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "data"))

import generate as gen  # noqa: E402
import engine  # noqa: E402
from engine import policy  # noqa: E402
from engine.taxonomy import COUNTERPARTIES_FILE, MERCHANT_CODES_FILE, load_taxonomy_data, read_json  # noqa: E402

KIT_VERSION = "1.0.0"
SEED = 20261018
TRAITS = OrderedDict([
    ("trait_a", (("a1", 0.5), ("a2", 0.3), ("a3", 0.2))),
    ("trait_b", (("b1", 0.5), ("b2", 0.5))),
    ("trait_c", (("c1", 0.25), ("c2", 0.25), ("c3", 0.25), ("c4", 0.25))),
])
RATIO_LINE = 0.8
ALPHA = 0.05
V_FAIL, V_WARN = 0.30, 0.10
ADEQUATE_TAGGED = 350
MIN_MEMBERS, MIN_TAGGED = 30, 5
SIZE_CAP = 1000000
PERMUTATIONS = 20

LAST_SIX = [(2026, m) for m in range(4, 10)]
RESTRICTED = (("worship", "8661", "SYN-PARISH-"), ("healthcare", "8062", "SYN-CLINIC-"),
              ("childcare", "8351", "SYN-NURSERY-"), ("charity", "8398", "SYN-APPEAL-"),
              ("pharmacy", "5912", "SYN-CHEMIST-"), ("school_fees", "8211", "SYN-ACADEMY-"))
PLANTED_RESTRICTED = {"a1": RESTRICTED[0], "a2": RESTRICTED[1], "a3": RESTRICTED[2]}
CORRIDOR = {"a1": "AE", "a2": "GB", "a3": "CA"}
PROTECTED_COLUMNS = ("nationality", "religion", "gender", "date_of_birth")
CANARIES = OrderedDict([
    ("canary-strong", {"category": "canary_strong", "rates": {"b1": 0.10, "b2": 0.60}, "must_fail": True}),
    ("canary-subtle", {"category": "canary_subtle", "rates": {"b1": 0.35, "b2": 0.50}, "must_fail": True}),
    ("canary-near-miss", {"category": "canary_near", "rates": {"b1": 0.405, "b2": 0.45}, "must_fail": False}),
])


# -- statistics ----------------------------------------------------------------------

def p_normal(z):
    return math.erfc(abs(z) / math.sqrt(2.0))


def _lcomb(n, k):
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def fisher_exact(a, n1, c, n2):
    """Two-sided Fisher's exact test: a of n1 tagged against c of n2."""
    k, total = a + c, n1 + n2
    observed = _lcomb(n1, a) + _lcomb(n2, c) - _lcomb(total, k)
    p = 0.0
    for x in range(max(0, k - n2), min(k, n1) + 1):
        log_p = _lcomb(n1, x) + _lcomb(n2, k - x) - _lcomb(total, k)
        if log_p <= observed + 1e-7:
            p += math.exp(log_p)
    return min(1.0, p)


def two_proportions(a, n1, c, n2):
    """p-value for a/n1 against c/n2: z-test, or Fisher's exact test when an expected cell is under 5."""
    k = a + c
    expected = [n1 * k / float(n1 + n2), n1 * (n1 + n2 - k) / float(n1 + n2),
                n2 * k / float(n1 + n2), n2 * (n1 + n2 - k) / float(n1 + n2)]
    if min(expected) < 5:
        return fisher_exact(a, n1, c, n2), "fisher"
    pooled = k / float(n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1.0 / n1 + 1.0 / n2))
    return (1.0 if se == 0 else p_normal((a / float(n1) - c / float(n2)) / se)), "z"


def gamma_q(s, x):
    """Regularised upper incomplete gamma function Q(s, x)."""
    if x <= 0:
        return 1.0
    log_front = -x + s * math.log(x) - math.lgamma(s)
    if x < s + 1:
        term = total = 1.0 / s
        a = s
        for _ in range(10000):
            a += 1
            term *= x / a
            total += term
            if abs(term) < abs(total) * 1e-15:
                break
        return max(0.0, 1.0 - total * math.exp(log_front))
    tiny = 1e-300
    b = x + 1 - s
    c = 1.0 / tiny
    d = 1.0 / b
    h = d
    for i in range(1, 10000):
        an = -i * (i - s)
        b += 2
        d = an * d + b
        d = tiny if abs(d) < tiny else d
        c = b + an / c
        c = tiny if abs(c) < tiny else c
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1) < 1e-15:
            break
    return math.exp(log_front) * h


def chi_square(table):
    """(statistic, degrees of freedom) of an r x c table of counts."""
    rows = [sum(r) for r in table]
    cols = [sum(c) for c in zip(*table)]
    n = float(sum(rows))
    stat = 0.0
    for i, r in enumerate(table):
        for j, observed in enumerate(r):
            expected = rows[i] * cols[j] / n
            if expected > 0:
                stat += (observed - expected) ** 2 / expected
    return stat, (len([r for r in rows if r]) - 1) * (len([c for c in cols if c]) - 1)


def cramers_v(table):
    stat, df = chi_square(table)
    n = float(sum(sum(r) for r in table))
    k = min(len([r for r in table if sum(r)]), len([c for c in zip(*table) if sum(c)])) - 1
    if k <= 0 or n == 0:
        return 0.0, 1.0
    return math.sqrt(stat / (n * k)), (gamma_q(df / 2.0, stat / 2.0) if df > 0 else 1.0)


def uncertainty(table):
    """Mutual information between rows and columns over the column entropy (columns are the groups)."""
    n = float(sum(sum(r) for r in table))
    rows = [sum(r) / n for r in table]
    cols = [sum(c) / n for c in zip(*table)]
    info = 0.0
    for i, r in enumerate(table):
        for j, observed in enumerate(r):
            if observed:
                p = observed / n
                info += p * math.log(p / (rows[i] * cols[j]))
    entropy = -sum(p * math.log(p) for p in cols if p > 0)
    return info / entropy if entropy > 0 else 0.0


def ratio_interval(x_low, n_low, x_high, n_high):
    """95% interval of (x_low/n_low) / (x_high/n_high) on the log scale (half a count added to zeros)."""
    a, c = (x_low or 0.5), (x_high or 0.5)
    ratio = (a / float(n_low)) / (c / float(n_high))
    se = math.sqrt(max(1.0 / a - 1.0 / n_low + 1.0 / c - 1.0 / n_high, 0.0))
    return ratio * math.exp(-1.96 * se), ratio * math.exp(1.96 * se)


# -- one tag against one attribute ---------------------------------------------------

def disparity(holders, groups, members, polarity):
    """holders: set of customer indices holding the tag; groups: index -> group;
    members: group -> count. Returns the measurements before the correction."""
    tagged = Counter(groups[i] for i in holders)
    eligible = [g for g in sorted(members) if members[g] >= MIN_MEMBERS]
    rates = OrderedDict((g, tagged[g] / float(members[g])) for g in sorted(members))
    row = OrderedDict([("polarity", polarity),
                       ("groups", OrderedDict((g, OrderedDict([("members", members[g]), ("tagged", tagged[g]),
                                                               ("rate", rates[g])])) for g in sorted(members)))])
    if len(eligible) < 2 or max(tagged[g] for g in eligible) < MIN_TAGGED:
        row.update(tier="insufficient", ratio=None)
        return row
    high = max(eligible, key=lambda g: (rates[g], g))
    low = min(eligible, key=lambda g: (rates[g], g))
    ratio = rates[low] / rates[high] if rates[high] > 0 else 1.0
    reference = low if polarity == "burden" else high
    comparisons = OrderedDict()
    for g in eligible:
        if g != reference:
            comparisons[g] = two_proportions(tagged[g], members[g], tagged[reference], members[reference])
    table = [[tagged[g] for g in eligible], [members[g] - tagged[g] for g in eligible]]
    v, v_p = cramers_v(table)
    harmed = {"benefit": low, "burden": high}.get(polarity)
    pair = low if reference == high else high
    row.update(tier="adequate" if tagged[high] >= ADEQUATE_TAGGED else "inconclusive", ratio=ratio,
               interval=ratio_interval(tagged[low], members[low], tagged[high], members[high]),
               low=low, high=high, reference=reference, harmed=harmed, pair=pair,
               p=OrderedDict((g, c[0]) for g, c in comparisons.items()),
               tests=OrderedDict((g, c[1]) for g, c in comparisons.items()),
               cramers_v=v, v_p=v_p, uncertainty=uncertainty(table))
    return row


def judge(row, tests_in_family):
    """Add the adjusted p-values and the verdict."""
    if row["tier"] == "insufficient":
        row["verdict"] = "insufficient"
        return row
    row["p_adjusted"] = OrderedDict((g, min(1.0, p * tests_in_family)) for g, p in row["p"].items())
    row["v_p_adjusted"] = min(1.0, row["v_p"] * tests_in_family)
    p_pair = row["p_adjusted"][row["pair"]]
    if (row["tier"] == "adequate" and row["ratio"] < RATIO_LINE and p_pair < ALPHA) or \
            (row["cramers_v"] >= V_FAIL and row["v_p_adjusted"] < ALPHA):
        row["verdict"] = "FAIL"
    elif row["tier"] == "inconclusive":
        row["verdict"] = "inconclusive"
    elif row["ratio"] < RATIO_LINE or row["cramers_v"] >= V_WARN:
        row["verdict"] = "WARN"
    else:
        row["verdict"] = "PASS"
    return row


def analyse(held, attributes, polarity):
    """held: tag -> set of customer indices; attributes: trait -> list of groups by index."""
    rows = OrderedDict()
    tests = 0
    for trait, groups in attributes.items():
        members = Counter(groups)
        for tag in held:
            row = disparity(held[tag], groups, members, polarity.get(tag, "neutral"))
            rows[(tag, trait)] = row
            tests += len(row.get("p", {}))
    for row in rows.values():
        judge(row, max(tests, 1))
    return rows, tests


def joint(combos, attributes):
    """Association between the combination of tags a customer holds and each attribute."""
    out = OrderedDict()
    counts = Counter(combos)
    label = [c if counts[c] >= 10 else "other" for c in combos]
    keys = sorted(set(label), key=str)
    for trait, groups in attributes.items():
        names = sorted(set(groups))
        cell = Counter(zip(label, groups))
        table = [[cell[(k, g)] for g in names] for k in keys]
        v, _ = cramers_v(table)
        out[trait] = OrderedDict([("combinations", len(keys)), ("cramers_v", v), ("uncertainty", uncertainty(table))])
    return out


# -- synthetic populations -----------------------------------------------------------

def _assign(rng, shares):
    roll = rng.unit()
    total = 0.0
    for group, share in shares:
        total += share
        if roll < total:
            return group
    return shares[-1][0]


def _allowed(person, year_month, day):
    when = gen.on(year_month, day)
    return when <= gen.AS_OF and (person.open_date is None or when >= person.open_date)


def population(seed, chunk, replicas, background, variant):
    """One chunk: (generator, attributes by customer id, restricted rows by customer id)."""
    combined = gen.Generator(seed + chunk)
    number = 0

    def take(g):
        nonlocal number
        for person in g.people:
            number += 1
            person.cid = "F{:03d}{:05d}".format(chunk, number)
            person.account = "SYN-ACC-F{:03d}{:05d}".format(chunk, number)
            person.expected = None
            person.gen = combined  # rows added from here on are written with the chunk
            combined.people.append(person)
        combined.rows_in_order.extend(g.rows_in_order)

    for k in range(replicas):
        g = gen.Generator(seed * 10 + chunk * 1000 + k)
        gen.scenarios(g)
        take(g)
    g = gen.Generator(seed * 10 + chunk * 1000 + 999)
    for n in range(1, background + 1):
        gen.background(g, n)
    take(g)

    trait_rng = gen.Rng(seed * 7 + chunk)
    attributes = OrderedDict()
    for person in combined.people:
        attributes[person.cid] = OrderedDict((t, _assign(trait_rng, shares)) for t, shares in TRAITS.items())

    # Monthly payments in restricted categories, for three customers in ten,
    # chosen independently of the attributes. Their dates and amounts are the
    # same in every variant; only the category, code and payee change.
    payment_rng = gen.Rng(seed * 11 + chunk)
    for person in combined.people:
        if not payment_rng.chance(0.3):
            continue
        category, mcc, payee = RESTRICTED[payment_rng.int(0, len(RESTRICTED) - 1)]
        payee_number = payment_rng.int(1, 99)
        amount = payment_rng.int(10, 80)
        if variant == "planted-proxy":
            category, mcc, payee = PLANTED_RESTRICTED[attributes[person.cid]["trait_a"]]
        for ym in LAST_SIX:
            if _allowed(person, ym, 3):
                person.add(gen.on(ym, 3), amount, "debit", "internet_banking", category,
                           "{}{:02d}".format(payee, payee_number), mcc=mcc)

    if variant == "planted-proxy":
        for person in combined.people:
            _relabel_countries(person, CORRIDOR[attributes[person.cid]["trait_a"]])

    if variant == "canary":
        canary_rng = gen.Rng(seed * 13 + chunk)
        for tag_id, canary in CANARIES.items():
            for person in combined.people:
                if canary_rng.chance(canary["rates"][attributes[person.cid]["trait_b"]]):
                    amount = canary_rng.int(15, 60)
                    for ym in LAST_SIX:
                        if _allowed(person, ym, 16):
                            person.add(gen.on(ym, 16), amount, "debit", "card_pos", canary["category"],
                                       "SYN-MERCHANT-0{:03d}".format(canary_rng.int(1, 400)), mcc="")
    for index, (person, row) in enumerate(combined.rows_in_order):
        row["seq"] = index
    return combined, attributes


def _relabel_countries(person, corridor):
    """Make the customer's first foreign country the corridor, one to one."""
    foreign = []
    for row in person.rows:
        if row["country"] != person.home_country and row["country"] not in foreign:
            foreign.append(row["country"])
    if not foreign or foreign[0] == corridor:
        return
    swap = {foreign[0]: corridor, corridor: foreign[0]}
    for row in person.rows:
        if row["country"] != person.home_country:
            row["country"] = swap.get(row["country"], row["country"])


def write_chunk(folder, combined, attributes, variant):
    gen.write(combined, folder)
    if variant == "planted-proxy":
        path = os.path.join(folder, "customers.csv")
        with open(path, encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
        rows[0] = rows[0] + list(PROTECTED_COLUMNS)
        for row in rows[1:]:
            values = attributes[row[0]]
            row.extend([values["trait_a"], values["trait_c"], values["trait_b"], "1980-01-01"])
        with open(path, "w", encoding="utf-8", newline="") as handle:
            csv.writer(handle, lineterminator="\n").writerows(rows)
    # The attributes go in their own file, which the engine is never given.
    with open(os.path.join(folder, "attributes.csv"), "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["customer_id"] + list(TRAITS))
        for cid, values in attributes.items():
            writer.writerow([cid] + list(values.values()))


def read_attributes(folder):
    with open(os.path.join(folder, "attributes.csv"), encoding="utf-8", newline="") as handle:
        return OrderedDict((row["customer_id"], OrderedDict((t, row[t]) for t in TRAITS))
                           for row in csv.DictReader(handle))


# -- taxonomies -----------------------------------------------------------------------

def real_taxonomy():
    return engine.load_taxonomy(engine.DEFAULT_TAXONOMY)


def canary_taxonomy():
    """The real taxonomy plus the test-only canary tags. Never written anywhere."""
    folder = os.path.dirname(engine.DEFAULT_TAXONOMY)
    raw = read_json(engine.DEFAULT_TAXONOMY)
    for tag_id, canary in CANARIES.items():
        raw["tags"].append(OrderedDict([
            ("id", tag_id), ("name", "Canary " + tag_id.split("-", 1)[1]), ("group", "spending-pattern"),
            ("description", "Test-only canary for the fairness kit."), ("polarity", "neutral"),
            ("fields", ["transactions.category", "transactions.direction", "transactions.posted_date"]),
            ("rule", {"all": [OrderedDict([
                ("id", "canary_months"), ("description", "months with a planted purchase"),
                ("metric", "months_where"), ("filter", {"direction": "debit", "category": canary["category"]}),
                ("window", {"months": 6}), ("monthly", {"measure": "count", "op": ">=", "value": 1}),
                ("op", ">="), ("value", 4)])]}),
            ("facts", []),
            ("reason", "planted purchases in {canary_months} of last 6 months"),
            ("limitations", ["Test only: never part of the taxonomy."]),
        ]))
    return load_taxonomy_data(raw, source="canary", verify_hash=False,
                              counterparties_raw=read_json(os.path.join(folder, COUNTERPARTIES_FILE)),
                              merchant_codes_raw=read_json(os.path.join(folder, MERCHANT_CODES_FILE)))


# -- running a scenario ---------------------------------------------------------------

def evaluate(folder, taxonomy):
    """Tag one chunk with the engine. Returns (ids, held tag sets by index, signature digest)."""
    result = engine.run(os.path.join(folder, "customers.csv"), os.path.join(folder, "transactions.csv"),
                        taxonomy, as_of=gen.AS_OF, lifecycle=False, evidence="held")
    ids, held = [], []
    digest = hashlib.sha256()
    for cid, tags in result.results.items():
        ids.append(cid)
        mine = set()
        for tag_id, r in tags.items():
            state = "held" if r.state is True else ("not_evaluated" if r.state is None else
                                                     ("suppressed" if r.suppressed_by else "not_met"))
            if state == "held":
                mine.add(tag_id)
            evidence = json.dumps(r.evidence, sort_keys=True, default=str) if state == "held" else ""
            digest.update(json.dumps([cid, tag_id, state, r.suppressed_by, r.reason if state == "held" else None,
                                      evidence, r.missing], sort_keys=True, default=str).encode("utf-8"))
        held.append(mine)
    return ids, held, digest.hexdigest()


def run_scenario(variant, chunks, replicas, background, seed, taxonomy, workdir):
    ids, held, attributes, digests = [], [], OrderedDict((t, []) for t in TRAITS), []
    for chunk in range(chunks):
        folder = os.path.join(workdir, "{}-{}".format(variant, chunk))
        os.makedirs(folder)
        combined, attrs = population(seed, chunk, replicas, background, variant)
        write_chunk(folder, combined, attrs, variant)
        chunk_ids, chunk_held, digest = evaluate(folder, taxonomy)
        joined = read_attributes(folder)
        for cid, tags in zip(chunk_ids, chunk_held):
            ids.append(cid)
            held.append(tags)
            for trait in TRAITS:
                attributes[trait].append(joined[cid][trait])
        digests.append(digest)
        shutil.rmtree(folder, ignore_errors=True)
    tags = list(taxonomy.by_id)
    by_tag = OrderedDict((t, set()) for t in tags)
    for index, mine in enumerate(held):
        for t in mine:
            by_tag[t].add(index)
    return {"variant": variant, "customers": len(ids), "held": by_tag, "attributes": attributes,
            "combos": [tuple(sorted(m)) for m in held], "digests": digests}


def permuted_flags(scenario, polarity, seed, rounds=PERMUTATIONS):
    """Shuffle the attributes and count the flags chance alone produces."""
    rng = gen.Rng(seed * 17)
    fails, warns = [], []
    for _ in range(rounds):
        shuffled = OrderedDict()
        for trait, groups in scenario["attributes"].items():
            values = list(groups)
            for i in range(len(values) - 1, 0, -1):
                j = rng.int(0, i)
                values[i], values[j] = values[j], values[i]
            shuffled[trait] = values
        rows, _ = analyse(scenario["held"], shuffled, polarity)
        verdicts = Counter(r["verdict"] for r in rows.values())
        fails.append(verdicts["FAIL"])
        warns.append(verdicts["WARN"])
    return sum(fails) / float(rounds), sum(warns) / float(rounds), max(fails)


def lint(taxonomy):
    """Rules that select a restricted or protected category (the taxonomy guard refuses these anyway)."""
    found = []
    for tag_id, tag in taxonomy.by_id.items():
        text = json.dumps({"rule": tag["rule"], "facts": tag.get("facts", [])}, default=str)
        for category in policy.PROXY_CATEGORIES | {policy.RESTRICTED_CATEGORY}:
            if '"category": "{}"'.format(category) in text:
                found.append((tag_id, category))
    return found


def run(chunks=1, replicas=40, background=3000, seed=SEED, permutations=PERMUTATIONS):
    real = real_taxonomy()
    canary = canary_taxonomy()
    polarity = {t: tag["polarity"] for t, tag in real.by_id.items()}
    polarity.update({t: "neutral" for t in CANARIES})
    workdir = tempfile.mkdtemp(prefix="tagging-fairness-")
    try:
        scenarios = OrderedDict()
        for variant, taxonomy in (("null", real), ("planted-proxy", real), ("canary", canary)):
            scenarios[variant] = run_scenario(variant, chunks, replicas, background, seed, taxonomy, workdir)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    results = OrderedDict()
    for variant, scenario in scenarios.items():
        rows, tests = analyse(scenario["held"], scenario["attributes"], polarity)
        results[variant] = {"rows": rows, "tests": tests, "joint": joint(scenario["combos"], scenario["attributes"]),
                            "customers": scenario["customers"]}
    chance_fail, chance_warn, chance_max_fail = permuted_flags(scenarios["null"], polarity, seed, permutations)
    null = scenarios["null"]
    joint_chance = joint_reference(null, seed)
    gate = OrderedDict()
    gate["null: no tag fails"] = not any(r["verdict"] == "FAIL" for r in results["null"]["rows"].values())
    gate["planted-proxy: output identical to null"] = scenarios["planted-proxy"]["digests"] == null["digests"]
    gate["planted-proxy: no tag fails"] = not any(
        r["verdict"] == "FAIL" for r in results["planted-proxy"]["rows"].values())
    for tag_id, canary_spec in CANARIES.items():
        verdict = results["canary"]["rows"][(tag_id, "trait_b")]["verdict"]
        if canary_spec["must_fail"]:
            gate["canary: {} fails on trait_b".format(tag_id)] = verdict == "FAIL"
        else:
            gate["canary: {} does not fail".format(tag_id)] = verdict != "FAIL"
    gate["lint: no rule selects a restricted category"] = not lint(real)
    rates = [len(h) / float(null["customers"]) for h in null["held"].values() if h]
    smallest_share = min(share for shares in TRAITS.values() for _, share in shares)
    needed = min(SIZE_CAP, int(math.ceil(ADEQUATE_TAGGED / (min(rates) * smallest_share)))) if rates else SIZE_CAP
    return OrderedDict([
        ("kit_version", KIT_VERSION), ("taxonomy_version", real.version), ("taxonomy_hash", real.content_hash),
        ("engine_version", engine.ENGINE_VERSION), ("seed", seed), ("chunks", chunks), ("replicas", replicas),
        ("background", background), ("customers", null["customers"]), ("results", results),
        ("chance", OrderedDict([("permutations", permutations), ("mean_fail", chance_fail),
                                ("mean_warn", chance_warn), ("max_fail", chance_max_fail)])),
        ("joint_chance", joint_chance), ("needed_customers", needed), ("gate", gate),
        ("passed", all(gate.values()))])


def joint_reference(scenario, seed):
    """The joint association a shuffled attribute gives (its chance level, for comparison)."""
    rng = gen.Rng(seed * 19)
    shuffled = OrderedDict()
    for trait, groups in scenario["attributes"].items():
        values = list(groups)
        for i in range(len(values) - 1, 0, -1):
            j = rng.int(0, i)
            values[i], values[j] = values[j], values[i]
        shuffled[trait] = values
    return joint(scenario["combos"], shuffled)


# -- the report -----------------------------------------------------------------------

def _pct(x):
    return "{:.1f}%".format(100.0 * x)


def _num(x, digits=3):
    return "–" if x is None else "{:.{}f}".format(x, digits)


def _p(x):
    return "<0.0001" if x < 0.0001 else "{:.4f}".format(x)


def markdown(result):
    out = ["# Fairness report (synthetic)", ""]
    out.append("Generated by `tools/fairness.py` (kit {}) for taxonomy {} (`{}`), engine {}. Regenerate with "
               "`python3 tools/fairness.py run --chunks {} --replicas {} --background {} --seed {} --out "
               "docs/fairness-report.md` (at this size, in CI only: `.github/workflows/fairness.yml`).".format(
                   result["kit_version"], result["taxonomy_version"], result["taxonomy_hash"],
                   result["engine_version"], result["chunks"], result["replicas"], result["background"],
                   result["seed"]))
    out.append("")
    out.append("**Everything here is synthetic.** The customers are generated, and so are their attributes: three "
               "stand-in traits (`trait_a` with three groups, `trait_b` with two, `trait_c` with four, shaped like "
               "age bands) that are written to a separate file the engine is never given. No real person's "
               "protected characteristics are used or inferred. A pass shows that the rules do not reach the "
               "pathways tested here; it is not proof that the tags are fair for a real population.")
    out.append("")
    out.append("## Result: {}".format("PASS" if result["passed"] else "FAIL"))
    out.append("")
    out.append("| Check | Result |")
    out.append("| --- | --- |")
    for check, ok in result["gate"].items():
        out.append("| {} | {} |".format(check, "pass" if ok else "**fail**"))
    out.append("")
    out.append("## Set-up")
    out.append("")
    out.append("- Seed {}; {} chunk(s) of {} copies of the 62 labelled scenarios and {:,} random background "
               "customers: {:,} customers per scenario, tagged as of {} by the engine itself.".format(
                   result["seed"], result["chunks"], result["replicas"], result["background"],
                   result["customers"], gen.AS_OF.isoformat()))
    out.append("- Scenarios: **null** (attributes independent of behaviour); **planted-proxy** (the same customers, "
               "with the attributes deciding the foreign country of their transactions, which restricted category "
               "and payee a monthly payment has, and protected columns in the customer file: things the engine "
               "must never use); **canary** (test-only tags reading a behaviour planted to follow `trait_b`).")
    out.append("- Gate: FAIL when the impact ratio is below {} and the Bonferroni-adjusted p-value below {} with at "
               "least {} customers tagged in the more-tagged group, or when Cramer's V is {:.2f} or more and "
               "significant. WARN when the ratio is below {} or V is {:.2f} or more. Below {} tagged the result is "
               "inconclusive; under {} members or {} tagged it is insufficient. Every tag is gated, whatever its "
               "polarity.".format(RATIO_LINE, ALPHA, ADEQUATE_TAGGED, V_FAIL, RATIO_LINE, V_WARN, ADEQUATE_TAGGED,
                                  MIN_MEMBERS, MIN_TAGGED))
    chance = result["chance"]
    out.append("- Chance: with the Bonferroni correction over {} comparisons, the chance of any false FAIL is at "
               "most 5%. Shuffling the attributes {} times gave on average {:.2f} FAIL and {:.1f} WARN verdicts "
               "(at most {} FAIL in one shuffle): about that many flags are noise.".format(
                   result["results"]["null"]["tests"], chance["permutations"], chance["mean_fail"],
                   chance["mean_warn"], chance["max_fail"]))
    out.append("- Size: for every tag to reach {} tagged customers in its smallest group, about {:,} customers "
               "are needed (capped at {:,}). The CI workflow `fairness.yml` runs at that scale.".format(
                   ADEQUATE_TAGGED, result["needed_customers"], SIZE_CAP))
    out.append("")
    for variant in ("null", "planted-proxy", "canary"):
        rows = result["results"][variant]["rows"]
        verdicts = Counter(r["verdict"] for r in rows.values())
        out.append("## Scenario: {}".format(variant))
        out.append("")
        out.append("{} tag and attribute pairs: {} PASS, {} WARN, {} FAIL, {} inconclusive, {} insufficient.".format(
            len(rows), verdicts["PASS"], verdicts["WARN"], verdicts["FAIL"], verdicts["inconclusive"],
            verdicts["insufficient"]))
        out.append("")
        if variant == "planted-proxy":
            out.append("The engine's output for every customer (states, reasons and evidence) was {} the null "
                       "scenario's, so every measurement equals the table above.".format(
                           "identical to" if result["gate"]["planted-proxy: output identical to null"]
                           else "**different from**"))
            out.append("")
            continue
        shown = rows.items()
        if variant == "canary":
            shown = [(k, r) for k, r in rows.items() if k[0] in CANARIES or r["verdict"] in ("FAIL", "WARN")]
            out.append("Shown: the canary tags, and any real tag that the planted purchases moved (these are "
                       "reported, not gated: the planted behaviour adds spending).")
            out.append("")
        out.append("| Tag | Polarity | Attribute | Rates by group | Ratio (95% interval) | Adj. p | V | U | Tier "
                   "| Verdict | Harmed group |")
        out.append("| --- | --- | --- | --- | --- | ---: | ---: | ---: | --- | --- | --- |")
        for (tag, trait), r in shown:
            rates = ", ".join("{} {}/{:,}".format(g, v["tagged"], v["members"]) for g, v in r["groups"].items())
            if r["tier"] == "insufficient":
                out.append("| `{}` | {} | {} | {} | – | – | – | – | insufficient | insufficient | – |".format(
                    tag, r["polarity"], trait, rates))
                continue
            out.append("| `{}` | {} | {} | {} | {} ({}–{}) | {} | {} | {} | {} | {} | {} |".format(
                tag, r["polarity"], trait, rates, _num(r["ratio"], 2), _num(r["interval"][0], 2),
                _num(r["interval"][1], 2), _p(r["p_adjusted"][r["pair"]]), _num(r["cramers_v"]),
                _num(r["uncertainty"], 4), r["tier"], r["verdict"], r["harmed"] or "–"))
        out.append("")
        out.append("Joint association between the combination of tags each customer holds and each attribute "
                   "(rare combinations pooled), against a shuffled attribute's value as the chance level:")
        out.append("")
        out.append("| Attribute | Combinations | V | V by chance | U | U by chance |")
        out.append("| --- | ---: | ---: | ---: | ---: | ---: |")
        for trait, j in result["results"][variant]["joint"].items():
            ref = result["joint_chance"][trait]
            out.append("| {} | {} | {} | {} | {} | {} |".format(trait, j["combinations"], _num(j["cramers_v"]),
                                                                _num(ref["cramers_v"]), _num(j["uncertainty"], 4),
                                                                _num(ref["uncertainty"], 4)))
        out.append("")
    out.append("## Limitations")
    out.append("")
    out.append("- Synthetic attributes and synthetic behaviour: the kit shows which pathways the rules can and cannot "
               "reach. It cannot show how a real population differs, and it never infers traits.")
    out.append("- Where a trait itself changes a behaviour a rule may use (for example how often money arrives from "
               "abroad), a tag on that behaviour will differ between groups. Whether such a difference is "
               "acceptable is the bank's decision under its regulator and data-protection law, case by case.")
    out.append("- Tags have no true outcome, so equal opportunity and equalised odds do not apply; the kit measures "
               "who receives a tag, not whether it was right.")
    out.append("- Many tag and attribute pairs are tested; WARN verdicts at about the shuffled rate are expected noise.")
    return "\n".join(out) + "\n"


def to_json(result):
    def clean(value):
        if isinstance(value, dict):
            return OrderedDict(("{}|{}".format(*k) if isinstance(k, tuple) else k, clean(v)) for k, v in value.items())
        if isinstance(value, (list, tuple)):
            return [clean(v) for v in value]
        if isinstance(value, set):
            return sorted(value)
        return value
    return json.dumps(clean(result), indent=1) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command")
    command = sub.add_parser("run", help="run the scenarios and write the report")
    command.add_argument("--chunks", type=int, default=1)
    command.add_argument("--replicas", type=int, default=40)
    command.add_argument("--background", type=int, default=3000)
    command.add_argument("--seed", type=int, default=SEED)
    command.add_argument("--permutations", type=int, default=PERMUTATIONS)
    command.add_argument("--out")
    command.add_argument("--json")
    args = parser.parse_args(argv)
    if args.command != "run":
        parser.print_help()
        return 2
    result = run(args.chunks, args.replicas, args.background, args.seed, args.permutations)
    text = markdown(result)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    else:
        sys.stdout.write(text)
    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(to_json(result))
    for check, ok in result["gate"].items():
        sys.stderr.write("{}: {}\n".format("pass" if ok else "FAIL", check))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

"""Tag cards: one generated Markdown card per tag, plus an index.

python3 -m engine.cards --out docs/tags     write the cards
python3 -m engine.cards --check docs/tags   exit 1 if a committed card differs

A card is generated from taxonomy/tags.json and never edited by hand: its
purpose, rule in words, conditions, data used, lifecycle group, intended and
prohibited uses, known limitations, owner and review date.
"""

import argparse
import os
import sys
from decimal import Decimal

from . import DEFAULT_TAXONOMY
from . import windows
from .evaluate import OP_WORDS, display, leaf_format, rule_text
from .taxonomy import iter_leaves, load_taxonomy

GENERATED = "Generated from `taxonomy/tags.json` by `python3 -m engine.cards`; do not edit by hand."
POLARITY_WORDS = {
    "benefit": "benefit (a customer may be offered something because of it)",
    "burden": "burden (a support signal; a customer could be disadvantaged if it were misused)",
    "neutral": "neutral (describes behaviour without implying an offer or a burden)",
}


def _cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def _needs(leaf, currency):
    if leaf["metric"] == "tag":
        return "yes" if leaf["value"] else "no"
    threshold = display(Decimal(str(leaf["value"])), leaf_format(leaf), currency)
    return "{} {}".format(OP_WORDS[leaf["op"]], threshold)


def _window(leaf):
    if leaf["metric"] == "ratio":
        return "{} vs {}".format(windows.describe(leaf["numerator"]["window"]),
                                 windows.describe(leaf["denominator"]["window"]))
    if "window" in leaf:
        return windows.describe(leaf["window"])
    if leaf["metric"] == "tenure_days":
        return "since the account opened"
    return "at the as-of date"


def card(taxonomy, tag):
    currency = taxonomy.base_currency
    governance = taxonomy.governance
    group = taxonomy.groups[tag["group"]]
    lines = [
        "# {} (`{}`)".format(tag["name"], tag["id"]),
        "",
        "- **Group:** {}".format(group["name"]),
        "- **Polarity:** {}".format(POLARITY_WORDS[tag["polarity"]]),
        "- **Taxonomy version:** {}".format(taxonomy.version),
    ]
    if tag["group"] == "financial-stress":
        lines.append("- **Support only:** offer help; never use for credit, pricing, collections or sales targeting.")
    lines += ["", "## Purpose", "", tag["description"], "",
              "## Rule in words", "", rule_text(tag["rule"], currency), "",
              "## Conditions", "", "| Condition | Window | Needs |", "| --- | --- | --- |"]
    for leaf in iter_leaves(tag["rule"]):
        lines.append("| {} | {} | {} |".format(_cell(leaf["description"]), _cell(_window(leaf)),
                                             _cell(_needs(leaf, currency))))
    facts = tag.get("facts", [])
    if facts:
        lines += ["", "Also shown as evidence, never part of the decision:", ""]
        for fact in facts:
            lines.append("- {} ({})".format(fact["description"], _window(fact)))
    lines += ["", "The reason shown to staff: \"{}\", with every placeholder filled from the evidence.".format(
        tag["reason"]), ""]
    lines += ["## Data used", ""]
    lines += ["- `{}`".format(field) for field in tag["fields"]]
    lines += ["", "No other column is read. Names, account numbers and protected-trait columns are never loaded.", ""]
    lines += ["## Lifecycle", ""]
    exclusive = taxonomy.exclusive_of.get(tag["id"])
    if exclusive:
        group = next(g for g in taxonomy.exclusive_groups if g["id"] == exclusive)
        lines.append("Part of the exclusive `{}` group: {}. Priority: {}.".format(
            exclusive, group["description"], ", ".join("`{}`".format(t) for t in group["priority"])))
        lines.append("")
    lines += ["Evaluated at the as-of date. History is recorded at month-end checkpoints: `entered_on` is the first "
              "month end of the current run at which the tag held; a tag that started after the last month end is "
              "\"new this month\".", ""]
    lines += ["## Intended use", "", governance["intended_use"], "",
              "## Prohibited uses", ""]
    lines += ["- {}".format(use) for use in governance["prohibited_uses"]]
    lines += ["", "## Known limitations", ""]
    lines += ["- {}".format(text) for text in tag["limitations"]]
    lines += ["", "## Owner and review", "",
              "- **Owner:** {}".format(governance["owner"]),
              "- **Review date:** {}".format(governance["review_date"]),
              "", "---", "", GENERATED, ""]
    return "\n".join(lines)


def index(taxonomy):
    lines = ["# Tag cards", "",
             "One card per tag in taxonomy {} ({} tags). Each card gives the purpose, the rule in words, the data "
             "used, the intended and prohibited uses, the known limitations, the owner and the review date.".format(
                 taxonomy.version, len(taxonomy.tags)), ""]
    for group_id, group in taxonomy.groups.items():
        tags = [t for t in taxonomy.tags if t["group"] == group_id]
        lines += ["## {}".format(group["name"]), "", group["description"], "",
                  "| Tag | What it means | Polarity |", "| --- | --- | --- |"]
        for tag in tags:
            lines.append("| [{}]({}.md) | {} | {} |".format(tag["name"], tag["id"], _cell(tag["description"]),
                                                          tag["polarity"]))
        lines.append("")
    lines += ["---", "", GENERATED, ""]
    return "\n".join(lines)


def render_all(taxonomy):
    """{file name: text} for every card and the index."""
    files = {"README.md": index(taxonomy)}
    for tag in taxonomy.tags:
        files[tag["id"] + ".md"] = card(taxonomy, tag)
    return files


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python3 -m engine.cards", description=__doc__.split("\n\n")[0])
    parser.add_argument("--taxonomy", default=DEFAULT_TAXONOMY)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--out", help="write the cards into this folder")
    action.add_argument("--check", help="compare the cards in this folder with the taxonomy; write nothing")
    args = parser.parse_args(argv)
    files = render_all(load_taxonomy(args.taxonomy))
    if args.check:
        stale = []
        present = set(os.listdir(args.check)) if os.path.isdir(args.check) else set()
        for name, text in sorted(files.items()):
            path = os.path.join(args.check, name)
            try:
                with open(path, encoding="utf-8") as handle:
                    if handle.read() != text:
                        stale.append(name)
            except OSError:
                stale.append(name)
        extra = sorted(n for n in present - set(files) if n.endswith(".md"))
        for name in stale + extra:
            sys.stderr.write("out of date: {}\n".format(name))
        return 1 if stale or extra else 0
    os.makedirs(args.out, exist_ok=True)
    for name, text in sorted(files.items()):
        with open(os.path.join(args.out, name), "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    sys.stdout.write("wrote {} cards and an index to {}\n".format(len(files) - 1, args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())

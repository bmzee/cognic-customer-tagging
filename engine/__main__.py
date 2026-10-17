"""Command line: python3 -m engine --customers C.csv --transactions T.csv [options]

Without --out-dir the engine is print-only: it reads the inputs and the
taxonomy, prints the result and writes nothing. With --out-dir it also
writes tagged.json and tagged.csv into that directory (never over an input).
"""

import argparse
import datetime
import os
import sys

from . import DEFAULT_TAXONOMY, DataError, TaxonomyError, load_taxonomy, output, run


def _parse_args(argv):
    parser = argparse.ArgumentParser(prog="python3 -m engine", description=__doc__.split("\n\n")[0])
    parser.add_argument("--customers", help="path to customers.csv")
    parser.add_argument("--transactions", help="path to transactions.csv")
    parser.add_argument("--taxonomy", default=DEFAULT_TAXONOMY, help="path to tags.json")
    parser.add_argument("--as-of", help="YYYY-MM-DD; default: the latest posted_date in the transactions")
    parser.add_argument("--customer", action="append", default=[], help="limit output to this customer id (repeatable)")
    parser.add_argument("--format", choices=("json", "text"), default="json", help="what to print (default json)")
    parser.add_argument("--why", metavar="TAG_ID", help="with --customer: explain why one tag does or does not apply")
    parser.add_argument("--include-unmet", action="store_true", help="also list tags whose rule was not met")
    parser.add_argument("--out-dir", help="write tagged.json and tagged.csv here (otherwise nothing is written)")
    parser.add_argument("--list-tags", action="store_true", help="print the taxonomy's tags and rules, then stop")
    return parser.parse_args(argv)


def _fail(message):
    sys.stderr.write("error: {}\n".format(message))
    return 2


def main(argv=None):
    args = _parse_args(argv)
    try:
        if args.list_tags:
            sys.stdout.write(output.list_tags_text(load_taxonomy(args.taxonomy)))
            return 0
        if not args.customers or not args.transactions:
            return _fail("--customers and --transactions are required")
        as_of = None
        if args.as_of:
            try:
                as_of = datetime.datetime.strptime(args.as_of, "%Y-%m-%d").date()
            except ValueError:
                return _fail("--as-of must be YYYY-MM-DD")
        result = run(args.customers, args.transactions, args.taxonomy, as_of)
    except (DataError, TaxonomyError, OSError) as exc:
        return _fail(str(exc))

    unknown = [cid for cid in args.customer if cid not in result.results]
    if unknown:
        return _fail("unknown customer id(s): {}".format(", ".join(unknown)))
    if args.why:
        if len(args.customer) != 1:
            return _fail("--why needs exactly one --customer")
        if args.why not in result.taxonomy.by_id:
            return _fail("unknown tag id: {}".format(args.why))

    ids = args.customer or None
    if args.out_dir:
        inputs = [os.path.abspath(p) for p in (args.customers, args.transactions, args.taxonomy)]
        os.makedirs(args.out_dir, exist_ok=True)
        json_path = os.path.join(args.out_dir, "tagged.json")
        csv_path = os.path.join(args.out_dir, "tagged.csv")
        for path in (json_path, csv_path):
            if os.path.abspath(path) in inputs:
                return _fail("refusing to overwrite an input file: {}".format(path))
        with open(json_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(output.to_json(output.run_record(result, ids, args.include_unmet)))
        with open(csv_path, "w", encoding="utf-8", newline="") as handle:
            handle.write(output.to_csv(result, ids))
        sys.stdout.write("wrote {} and {} ({} customers, as of {})\n".format(
            json_path, csv_path, len(result.results), result.as_of.isoformat()))
        return 0

    if args.format == "text":
        for cid in (ids or list(result.results)):
            sys.stdout.write(output.explain_text(result, cid, args.why))
    else:
        sys.stdout.write(output.to_json(output.run_record(result, ids, args.include_unmet)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""python3 -m server --store PATH [--taxonomy PATH]: serve the reader over stdio."""

import argparse
import io
import sys

from engine import DEFAULT_TAXONOMY, TaxonomyError, load_taxonomy

from .protocol import Server, serve
from .tools import Reader


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python3 -m server", description=__doc__.split(":", 1)[1].strip())
    parser.add_argument("--store", required=True, help="the profile store, opened read-only")
    parser.add_argument("--taxonomy", default=DEFAULT_TAXONOMY, help="path to tags.json")
    args = parser.parse_args(argv)
    try:
        taxonomy = load_taxonomy(args.taxonomy)
    except (TaxonomyError, OSError) as exc:
        sys.stderr.write("error: {}\n".format(exc))
        return 2
    stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", newline="\n")
    serve(Server(Reader(args.store, taxonomy)), stdin, stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())

import argparse
import sys
from datetime import date, datetime

import pytz

from . import commit_reveal, config, extractor


def _parse_date(s: str) -> date:
    # print(f"parsing CLI date value: {s}")
    return date.fromisoformat(s)


def _today_et_date() -> date:
    # print("calculating current date in ET")
    et = pytz.timezone("America/New_York")
    return datetime.now(et).date()


def cmd_commit(args: argparse.Namespace) -> int:
    # print(f"cmd_commit invoked with args: {args}")
    d = _parse_date(args.date) if args.date else _today_et_date()
    changed = commit_reveal.perform_commit(d, enforce_window=not args.force)
    print(f"commit: date={d} changed={changed}")
    return 0


def cmd_reveal(args: argparse.Namespace) -> int:
    # print(f"cmd_reveal invoked with args: {args}")
    d = _parse_date(args.date) if args.date else _today_et_date()
    changed = commit_reveal.perform_reveal(d, enforce_window=not args.force)
    print(f"reveal: date={d} changed={changed}")
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    # print(f"cmd_extract invoked with args: {args}")
    d = _parse_date(args.date) if args.date else _today_et_date()
    window = args.window or config.EXTRACT_WINDOW
    bits = args.bits or config.EXTRACT_BITS
    changed = extractor.run_for_date(d, window=window, out_bits=bits)
    print(f"extract: date={d} changed={changed} window={window} bits={bits}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="rrpe-drbg")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_commit = sub.add_parser("commit", help="Commit predictions for the trading day")
    p_commit.add_argument("--date", help="Trade date YYYY-MM-DD", default=None)
    p_commit.add_argument("--force", action="store_true", help="Ignore time window checks")
    p_commit.set_defaults(func=cmd_commit)

    p_reveal = sub.add_parser("reveal", help="Reveal predictions after close and verify commitments")
    p_reveal.add_argument("--date", help="Trade date YYYY-MM-DD", default=None)
    p_reveal.add_argument("--force", action="store_true", help="Ignore time window checks")
    p_reveal.set_defaults(func=cmd_reveal)

    p_extract = sub.add_parser("extract", help="Extract randomness from accumulated symbols")
    p_extract.add_argument("--date", help="Trade date YYYY-MM-DD", default=None)
    p_extract.add_argument("--window", type=int, default=None)
    p_extract.add_argument("--bits", type=int, default=None)
    p_extract.set_defaults(func=cmd_extract)

    args = parser.parse_args(argv)
    # print(f"parsed arguments: {args}")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())


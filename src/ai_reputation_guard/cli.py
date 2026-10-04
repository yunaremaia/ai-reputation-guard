"""CLI entry point for ai-reputation-guard."""
import argparse
import math
import sys


def _positive_int(value):
    """argparse ``type`` for a threshold that must be a whole number > 0.

    ``type=int`` alone only guarantees the token parses as a float; it happily
    accepts ``0`` and ``-5``. Those reach the scanner as thresholds that can
    never fire, so the domain is enforced here, at the parser.
    """
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        # Keeps argparse's conventional wording for non-numeric input.
        raise argparse.ArgumentTypeError(f"invalid int value: {value!r}") from None
    if parsed <= 0:
        raise argparse.ArgumentTypeError(f"must be greater than 0, got {parsed}")
    return parsed


def _ratio(value):
    """argparse ``type`` for a ratio, constrained to the closed interval [0.0, 1.0].

    ``type=float`` accepts ``nan``, ``inf`` and out-of-range ratios. ``nan`` is
    the dangerous one: every comparison against it is silently False, so a
    reputation signal that should fire quietly never does — and ``json.dumps``
    would emit bare ``NaN``, which is not valid JSON per RFC 8259.
    """
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        # Keeps argparse's conventional wording for non-numeric input.
        raise argparse.ArgumentTypeError(f"invalid float value: {value!r}") from None
    if not math.isfinite(parsed):
        raise argparse.ArgumentTypeError(f"ratio must be finite, got {value!r}")
    if not 0.0 <= parsed <= 1.0:
        raise argparse.ArgumentTypeError(f"ratio must be between 0.0 and 1.0, got {parsed}")
    return parsed


def main():
    parser = argparse.ArgumentParser(
        prog="ai-reputation-guard",
        description="Detect AI-assisted reputation laundering on GitHub",
    )
    sub = parser.add_subparsers(dest="command")

    # scan
    scan_parser = sub.add_parser("scan", help="Scan a GitHub account")
    scan_parser.add_argument("username", help="GitHub username to scan")
    scan_parser.add_argument("--pr-threshold", type=_positive_int, default=10)
    scan_parser.add_argument("--trivial-ratio", type=_ratio, default=0.7)
    scan_parser.add_argument("--days", type=_positive_int, default=30)
    scan_parser.add_argument("--format", choices=["cli", "json", "sarif"], default="cli")
    scan_parser.add_argument("--output", help="Output file path")

    # batch
    batch_parser = sub.add_parser("batch", help="Batch scan multiple accounts")
    batch_parser.add_argument("--members-file", required=True)
    batch_parser.add_argument("--format", choices=["cli", "json", "sarif"], default="cli")
    batch_parser.add_argument("--output")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    print(f"[ai-reputation-guard] Command '{args.command}' recognized — implement scanner logic next.")


if __name__ == "__main__":
    main()

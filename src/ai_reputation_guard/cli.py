"""CLI entry point for ai-reputation-guard."""
import argparse
import math
import os
import sys
from pathlib import Path

from ai_reputation_guard import scanner


def _positive_int(value, maximum=None):
    """argparse ``type`` for a threshold that must be a whole number > 0.

    ``type=int`` alone only guarantees the token parses as a float; it happily
    accepts ``0`` and ``-5``. Those reach the scanner as thresholds that can
    never fire, so the domain is enforced here, at the parser.

    ``maximum`` bounds the value from above for callers whose ceiling is lower
    than "any positive int" -- ``--days`` alone, whose window is arithmetic on
    ``date`` (#22). Shared by every caller that names a maximum, so the bound
    cannot drift between them.
    """
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        # Keeps argparse's conventional wording for non-numeric input.
        raise argparse.ArgumentTypeError(f"invalid int value: {value!r}") from None
    if parsed <= 0:
        raise argparse.ArgumentTypeError(f"must be greater than 0, got {parsed}")
    if maximum is not None and parsed > maximum:
        raise argparse.ArgumentTypeError(f"must be at most {maximum}, got {parsed}")
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


def _write(text, output):
    """Print ``text``, or write it to ``output`` if a path was given.

    Returns False when the destination cannot be written, so a "successful"
    scan cannot exit 0 while leaving no artifact behind (#19).
    """
    if not output:
        print(text)
        return True
    path = Path(output)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot write report to {path}: {exc}", file=sys.stderr)
        return False
    print(f"Report written to {path}")
    return True


def _run_scan(args):
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    try:
        data = scanner.fetch_account(args.username, args.days, token=token)
    except scanner.ScanError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    report = scanner.analyze(
        data["prs"],
        data["issues_opened"],
        username=data["user"].get("login", args.username),
        days=args.days,
        pr_threshold=args.pr_threshold,
        trivial_ratio=args.trivial_ratio,
    )
    if not report["signals_collected"]:
        # Nothing to judge. Exiting 0 here would read as "this account is clean".
        # Merged PRs are what every signal is computed from, so an issue-only
        # account lands here too: 0 issues is not a verdict either (#23).
        print(
            f"error: no signals collected for {report['username']} in the last "
            f"{args.days} days (0 merged PRs, {report['issues_opened']} issues "
            f"opened); nothing was scanned",
            file=sys.stderr,
        )
        return 1
    return 0 if _write(scanner.render(report, args.format), args.output) else 1


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
    scan_parser.add_argument(
        "--days",
        type=lambda value: _positive_int(value, scanner.MAX_WINDOW_DAYS),
        default=30,
    )
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

    if args.command == "scan":
        sys.exit(_run_scan(args))

    # `batch` is still a stub (#7); it says so, in ASCII, and stops there.
    print(f"[ai-reputation-guard] Command '{args.command}' recognized - "
          f"batch scanning is not implemented yet, see issue #7.")


if __name__ == "__main__":
    main()

"""CLI entry point for ai-reputation-guard."""
import argparse
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="ai-reputation-guard",
        description="Detect AI-assisted reputation laundering on GitHub",
    )
    sub = parser.add_subparsers(dest="command")

    # scan
    scan_parser = sub.add_parser("scan", help="Scan a GitHub account")
    scan_parser.add_argument("username", help="GitHub username to scan")
    scan_parser.add_argument("--pr-threshold", type=int, default=10)
    scan_parser.add_argument("--trivial-ratio", type=float, default=0.7)
    scan_parser.add_argument("--days", type=int, default=30)
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

"""Tests for the ai-reputation-guard CLI.

The scanner logic is still a placeholder (see issues #7 and #8), so these tests
pin the contract that exists today: argument parsing, exit codes, and the
placeholder output. They are written to keep passing as the scanner is
implemented, and they touch no network.
"""

import pytest

from ai_reputation_guard import __version__
from ai_reputation_guard import cli


def run_cli():
    """Invoke ``main()`` against the patched ``sys.argv``; return its exit code.

    The command line itself is set by the ``cli_args`` fixture, so this only
    has to translate argparse's ``SystemExit`` into a plain integer.
    """
    try:
        cli.main()
    except SystemExit as exc:
        return exc.code
    return 0


@pytest.fixture(autouse=True)
def cli_args(monkeypatch):
    """Point ``sys.argv`` at the per-test command line."""

    def _set(argv):
        monkeypatch.setattr("sys.argv", ["ai-reputation-guard", *argv])

    return _set


# --- package metadata -------------------------------------------------------


def test_version_is_exposed():
    assert __version__


# --- top-level help ---------------------------------------------------------


def test_no_command_prints_help_and_exits_nonzero(cli_args, capsys):
    cli_args([])
    assert run_cli() == 1
    assert "usage: ai-reputation-guard" in capsys.readouterr().out


def test_help_flag_exits_cleanly(cli_args, capsys):
    cli_args(["--help"])
    assert run_cli() == 0
    out = capsys.readouterr().out
    assert "scan" in out
    assert "batch" in out


def test_help_documents_the_description(cli_args, capsys):
    cli_args(["--help"])
    run_cli()
    assert "reputation laundering" in capsys.readouterr().out


# --- scan -------------------------------------------------------------------


def test_scan_accepts_username(cli_args, capsys):
    cli_args(["scan", "octocat"])
    assert run_cli() == 0
    assert "Command 'scan' recognized" in capsys.readouterr().out


def test_scan_without_username_is_an_error(cli_args, capsys):
    cli_args(["scan"])
    assert run_cli() == 2
    assert "usage: ai-reputation-guard scan" in capsys.readouterr().err


def test_scan_rejects_unknown_format(cli_args, capsys):
    cli_args(["scan", "octocat", "--format", "bogus"])
    assert run_cli() == 2
    assert "invalid choice" in capsys.readouterr().err


@pytest.mark.parametrize("fmt", ["cli", "json", "sarif"])
def test_scan_accepts_each_declared_format(cli_args, fmt):
    cli_args(["scan", "octocat", "--format", fmt])
    assert run_cli() == 0


def test_scan_rejects_non_numeric_threshold(cli_args, capsys):
    cli_args(["scan", "octocat", "--pr-threshold", "many"])
    assert run_cli() == 2
    assert "invalid int value" in capsys.readouterr().err


def test_scan_rejects_non_numeric_trivial_ratio(cli_args, capsys):
    cli_args(["scan", "octocat", "--trivial-ratio", "high"])
    assert run_cli() == 2
    assert "invalid float value" in capsys.readouterr().err


# --- scan: threshold domain -------------------------------------------------
#
# The scanner is still a placeholder (#7), but the thresholds it already accepts
# are part of the CLI contract. An out-of-domain threshold must be rejected at
# the parser rather than carried into the scanner: `nan` in particular makes
# every downstream comparison silently False, so a reputation signal that
# should fire quietly never does.


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "1e400"])
def test_scan_rejects_non_finite_trivial_ratio(cli_args, capsys, value):
    # The `=` form is used deliberately: argparse's negative-number heuristic
    # treats a bare `-inf` as an option string, so the space form never reaches
    # the validator at all (it errors "expected one argument" — still exit 2,
    # but for a reason that says nothing about the domain).
    cli_args(["scan", "octocat", f"--trivial-ratio={value}"])
    assert run_cli() == 2
    err = capsys.readouterr().err
    assert "ratio must be finite" in err
    # The offending token itself must be echoed, so the user sees what was wrong.
    assert f"got {value!r}" in err


@pytest.mark.parametrize("value", ["5.0", "1.5", "-0.5", "-1"])
def test_scan_rejects_out_of_range_trivial_ratio(cli_args, capsys, value):
    cli_args(["scan", "octocat", "--trivial-ratio", value])
    assert run_cli() == 2
    err = capsys.readouterr().err
    assert "ratio must be between 0.0 and 1.0" in err
    assert f"got {float(value)}" in err


@pytest.mark.parametrize("value", ["0.0", "0.5", "1.0"])
def test_scan_accepts_in_domain_trivial_ratio(cli_args, capsys, value):
    """The bounds are inclusive: 0.0 and 1.0 are legitimate ratios."""
    cli_args(["scan", "octocat", "--trivial-ratio", value])
    assert run_cli() == 0
    assert "Command 'scan' recognized" in capsys.readouterr().out


@pytest.mark.parametrize("value", ["0", "-1", "-5"])
def test_scan_rejects_non_positive_days(cli_args, capsys, value):
    cli_args(["scan", "octocat", "--days", value])
    assert run_cli() == 2
    err = capsys.readouterr().err
    assert "must be greater than 0" in err
    assert f"got {int(value)}" in err


@pytest.mark.parametrize("value", ["0", "-1"])
def test_scan_rejects_non_positive_pr_threshold(cli_args, capsys, value):
    cli_args(["scan", "octocat", "--pr-threshold", value])
    assert run_cli() == 2
    err = capsys.readouterr().err
    assert "must be greater than 0" in err
    assert f"got {int(value)}" in err


def test_scan_accepts_positive_thresholds_together(cli_args, capsys):
    cli_args(
        [
            "scan",
            "octocat",
            "--days",
            "1",
            "--pr-threshold",
            "1",
            "--trivial-ratio",
            "1.0",
        ]
    )
    assert run_cli() == 0
    assert "Command 'scan' recognized" in capsys.readouterr().out


def test_scan_rejects_non_finite_ratio_before_writing_a_report(cli_args, capsys):
    """A rejected ratio must not reach stdout. A NaN in a JSON report is not
    valid JSON per RFC 8259, and would fail every strict consumer."""
    cli_args(["scan", "octocat", "--trivial-ratio", "nan", "--format", "json"])
    assert run_cli() == 2
    captured = capsys.readouterr()
    assert "NaN" not in captured.out
    assert captured.out == ""


def test_scan_accepts_output_path(cli_args, capsys):
    cli_args(["scan", "octocat", "--output", "report.json"])
    assert run_cli() == 0
    assert "Command 'scan' recognized" in capsys.readouterr().out


# --- batch ------------------------------------------------------------------


def test_batch_requires_members_file(cli_args, capsys):
    cli_args(["batch"])
    assert run_cli() == 2
    assert "--members-file" in capsys.readouterr().err


def test_batch_accepts_members_file(cli_args, capsys):
    argv = ["batch", "--members-file", "members.txt"]
    cli_args(argv)
    assert run_cli() == 0
    assert "Command 'batch' recognized" in capsys.readouterr().out


def test_batch_accepts_output_path(cli_args, capsys):
    argv = ["batch", "--members-file", "members.txt", "--output", "out.json"]
    cli_args(argv)
    assert run_cli() == 0
    assert "Command 'batch' recognized" in capsys.readouterr().out


# --- unknown commands -------------------------------------------------------


def test_unknown_subcommand_is_an_error(cli_args, capsys):
    cli_args(["scanall"])
    assert run_cli() == 2
    assert "invalid choice" in capsys.readouterr().err
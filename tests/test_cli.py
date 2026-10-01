"""Tests for the ai-reputation-guard CLI.

The scanner logic is still a placeholder (see issues #7 and #8), so these tests
pin the contract that exists today: argument parsing, exit codes, and the
placeholder output. They are written to keep passing as the scanner is
implemented, and they touch no network.
"""

import pytest

from src import __version__
from src import cli


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
"""Tests for the ai-reputation-guard CLI.

These pin the CLI contract: argument parsing, exit codes, where the report is
written, and what happens when the API call fails. The GitHub API is stubbed at
``scanner.fetch_account`` so the suite never touches the network; see
``tests/test_scanner.py`` for the collection, scoring and rendering details.
"""

import io
import json

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


# --- stubs ------------------------------------------------------------------


def merged_pr(merged_at, created_at, repo="acme/one", number=1, title="fix typo in docs"):
    """One search-API pull-request item, shaped like GitHub's payload."""
    return {
        "created_at": created_at,
        "repository_url": f"https://api.github.com/repos/{repo}",
        "title": title,
        "html_url": f"https://github.com/{repo}/pull/{number}",
        "pull_request": {"merged_at": merged_at},
    }


@pytest.fixture
def stub_api(monkeypatch):
    """Replace the GitHub call with canned data; returns a config dict.

    ``stub_api.prs`` and ``stub_api.issues`` shape the fake response, and
    ``stub_api.error`` makes the call fail instead, so every failure path below
    is exercised without a live request.
    """
    config = {"prs": [merged_pr("2024-05-02T10:00:00Z", "2024-05-02T09:00:00Z")],
              "issues": 2, "error": None}
    calls = []

    def fake_fetch(username, days, **kwargs):
        calls.append((username, days, kwargs))
        if config["error"] is not None:
            raise config["error"]
        return {"user": {"login": username}, "prs": config["prs"], "issues_opened": config["issues"]}

    monkeypatch.setattr("ai_reputation_guard.scanner.fetch_account", fake_fetch)
    config["calls"] = calls
    return config


@pytest.fixture
def ascii_stdout(monkeypatch):
    """A stdout that refuses any non-ASCII byte, like a legacy POSIX locale.

    This is the condition bug #20 reported: ``--help`` is pure ASCII and passes,
    while the scan report contained an em-dash and died with
    ``UnicodeEncodeError``.
    """
    stream = io.TextIOWrapper(io.BytesIO(), encoding="ascii")
    monkeypatch.setattr("sys.stdout", stream)
    return stream


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


def test_scan_accepts_username(cli_args, stub_api, capsys):
    cli_args(["scan", "octocat"])
    assert run_cli() == 0
    out = capsys.readouterr().out
    assert "octocat" in out
    assert "Score" in out


def test_scan_passes_the_window_to_the_scanner(cli_args, stub_api):
    cli_args(["scan", "octocat", "--days", "7"])
    assert run_cli() == 0
    username, days, _ = stub_api["calls"][0]
    assert (username, days) == ("octocat", 7)


def test_scan_threshold_changes_the_verdict(cli_args, stub_api, capsys):
    """The threshold must reach the analysis, not just parse."""
    burst = [merged_pr(f"2024-05-02T{h:02d}:00:00Z", "2024-05-02T00:00:00Z", number=h)
             for h in range(12)]
    stub_api["prs"] = burst
    cli_args(["scan", "octocat", "--pr-threshold", "5"])
    assert run_cli() == 0
    assert "volume_burst" in capsys.readouterr().out

    cli_args(["scan", "octocat", "--pr-threshold", "50"])
    assert run_cli() == 0
    assert "volume_burst" not in capsys.readouterr().out


def test_scan_reads_the_token_from_the_environment(cli_args, stub_api, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "env-token")
    monkeypatch.delenv("GH_TOKEN", raising=False)
    cli_args(["scan", "octocat"])
    assert run_cli() == 0
    assert stub_api["calls"][0][2]["token"] == "env-token"


def test_scan_falls_back_to_gh_token(cli_args, stub_api, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GH_TOKEN", "fallback-token")
    cli_args(["scan", "octocat"])
    assert run_cli() == 0
    assert stub_api["calls"][0][2]["token"] == "fallback-token"


def test_scan_never_prints_the_token(cli_args, stub_api, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_TOKEN", "super-secret")
    cli_args(["scan", "octocat"])
    assert run_cli() == 0
    captured = capsys.readouterr()
    assert "super-secret" not in captured.out
    assert "super-secret" not in captured.err


def test_scan_without_username_is_an_error(cli_args, capsys):
    cli_args(["scan"])
    assert run_cli() == 2
    assert "usage: ai-reputation-guard scan" in capsys.readouterr().err


def test_scan_rejects_unknown_format(cli_args, capsys):
    cli_args(["scan", "octocat", "--format", "bogus"])
    assert run_cli() == 2
    assert "invalid choice" in capsys.readouterr().err


@pytest.mark.parametrize("fmt", ["cli", "json", "sarif"])
def test_scan_accepts_each_declared_format(cli_args, stub_api, capsys, fmt):
    cli_args(["scan", "octocat", "--format", fmt])
    assert run_cli() == 0
    assert capsys.readouterr().out.strip()


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
def test_scan_accepts_in_domain_trivial_ratio(cli_args, stub_api, capsys, value):
    """The bounds are inclusive: 0.0 and 1.0 are legitimate ratios."""
    cli_args(["scan", "octocat", "--trivial-ratio", value])
    assert run_cli() == 0
    assert "Score" in capsys.readouterr().out


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


def test_scan_accepts_positive_thresholds_together(cli_args, stub_api, capsys):
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
    assert "Score" in capsys.readouterr().out


def test_scan_rejects_non_finite_ratio_before_writing_a_report(cli_args, capsys):
    """A rejected ratio must not reach stdout. A NaN in a JSON report is not
    valid JSON per RFC 8259, and would fail every strict consumer."""
    cli_args(["scan", "octocat", "--trivial-ratio", "nan", "--format", "json"])
    assert run_cli() == 2
    captured = capsys.readouterr()
    assert "NaN" not in captured.out
    assert captured.out == ""


def test_scan_accepts_output_path(cli_args, stub_api, tmp_path, capsys):
    report = tmp_path / "report.json"
    cli_args(["scan", "octocat", "--output", str(report)])
    assert run_cli() == 0
    assert "octocat" in report.read_text()


# --- scan: honest failures --------------------------------------------------
#
# A scan that cannot see the account must not exit 0. Every one of these used to
# be indistinguishable from a successful scan.


def test_unknown_user_exits_nonzero(cli_args, stub_api, capsys):
    from ai_reputation_guard import scanner

    stub_api["error"] = scanner.ScanError("GitHub user 'ghost' not found")
    cli_args(["scan", "ghost"])
    assert run_cli() == 1
    assert "not found" in capsys.readouterr().err


def test_rate_limited_scan_exits_nonzero(cli_args, stub_api, capsys):
    from ai_reputation_guard import scanner

    stub_api["error"] = scanner.ScanError("GitHub API rate limit exceeded; set GITHUB_TOKEN")
    cli_args(["scan", "octocat"])
    assert run_cli() == 1
    assert "rate limit" in capsys.readouterr().err


def test_network_error_exits_nonzero(cli_args, stub_api, capsys):
    from ai_reputation_guard import scanner

    stub_api["error"] = scanner.ScanError("network error talking to GitHub: no route to host")
    cli_args(["scan", "octocat"])
    assert run_cli() == 1
    assert "network" in capsys.readouterr().err


def test_a_failing_scan_writes_no_report(cli_args, stub_api, tmp_path, capsys):
    """A stale report must not survive a scan that failed (#19)."""
    from ai_reputation_guard import scanner

    report = tmp_path / "report.json"
    report.write_text("{\"stale\": true}")
    stub_api["error"] = scanner.ScanError("GitHub user 'ghost' not found")
    cli_args(["scan", "ghost", "--output", str(report)])
    assert run_cli() == 1
    assert json.loads(report.read_text()) == {"stale": True}


# --- scan: --output ---------------------------------------------------------


def test_scan_writes_the_report_to_output(cli_args, stub_api, tmp_path, capsys):
    report = tmp_path / "report.json"
    cli_args(["scan", "octocat", "--format", "json", "--output", str(report)])
    assert run_cli() == 0
    payload = json.loads(report.read_text())
    assert payload["username"] == "octocat"
    assert payload["pr_count"] == 1


def test_output_file_is_not_also_printed_to_stdout(cli_args, stub_api, tmp_path, capsys):
    """With --output the report goes to the file, not to stdout as well."""
    report = tmp_path / "report.json"
    cli_args(["scan", "octocat", "--format", "json", "--output", str(report)])
    assert run_cli() == 0
    out = capsys.readouterr().out
    assert str(report) in out
    assert '"score"' not in out


def test_output_creates_missing_parent_directories(cli_args, stub_api, tmp_path):
    report = tmp_path / "nested" / "dir" / "report.json"
    cli_args(["scan", "octocat", "--format", "json", "--output", str(report)])
    assert run_cli() == 0
    assert report.exists()


def test_unwritable_output_path_exits_nonzero(cli_args, stub_api, tmp_path, capsys):
    """A report that cannot be written must not read as a successful scan (#19)."""
    target = tmp_path / "a-directory"
    target.mkdir()
    cli_args(["scan", "octocat", "--output", str(target)])
    assert run_cli() == 1
    assert "cannot write report" in capsys.readouterr().err.lower()


# --- scan: nothing to report ------------------------------------------------


def test_scan_with_no_signals_exits_nonzero(cli_args, stub_api, tmp_path, capsys):
    """Zero PRs and zero issues is a scan that saw nothing, not a clean account."""
    stub_api["prs"] = []
    stub_api["issues"] = 0
    report = tmp_path / "report.json"
    cli_args(["scan", "octocat", "--output", str(report)])
    assert run_cli() == 1
    assert "no signals" in capsys.readouterr().err.lower()
    assert not report.exists()


# --- scan: non-UTF-8 stdout (#20) -------------------------------------------


def test_scan_report_survives_an_ascii_stdout(cli_args, stub_api, ascii_stdout, capsys):
    """#20: an em-dash in the report raised UnicodeEncodeError and exit 1."""
    cli_args(["scan", "octocat"])
    assert run_cli() == 0


def test_batch_notice_survives_an_ascii_stdout(cli_args, capsys, ascii_stdout):
    """The placeholder notice has an em-dash too, and batch reaches stdout."""
    cli_args(["batch", "--members-file", "members.txt"])
    assert run_cli() == 0


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
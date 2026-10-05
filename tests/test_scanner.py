"""Tests for signal collection, scoring and rendering.

Every test drives the scanner through an injected ``opener``, so the suite never
touches the network and stays deterministic. The live API is exercised manually,
not from CI.
"""

import io
import json
import urllib.error
import urllib.parse

import pytest

from ai_reputation_guard import scanner


# --- fixtures / helpers -----------------------------------------------------


class FakeResponse:
    """Minimal stand-in for the object returned by ``urlopen``."""

    def __init__(self, payload):
        self._payload = json.dumps(payload).encode()

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class RecordingOpener:
    """Records every request and answers from a ``{url_fragment: payload}`` map."""

    def __init__(self, routes, error=None):
        self.routes = routes
        self.error = error
        self.requests = []

    def __call__(self, request, timeout=None):
        # The real query string is percent-encoded; record and match the
        # readable form so a route key can be a literal "type:pr".
        url = urllib.parse.unquote(request.full_url)
        self.requests.append(url)
        if self.error is not None:
            raise self.error
        for fragment, payload in self.routes.items():
            if fragment in url:
                return FakeResponse(payload)
        raise AssertionError(f"unexpected URL: {url}")


def http_error(status, headers=None, body=b"{}"):
    return urllib.error.HTTPError(
        url="https://api.github.com/x",
        code=status,
        msg="boom",
        hdrs=_Headers(headers or {}),
        fp=io.BytesIO(body),
    )


class _Headers(dict):
    """Stand-in for ``email.message.Message`` with case-insensitive ``get``."""

    def get(self, key, default=None):
        for name, value in self.items():
            if name.lower() == key.lower():
                return value
        return default


def pr(merged_at, created_at, repo="acme/one", number=1, title="fix typo in docs"):
    return {
        "created_at": created_at,
        "repository_url": f"https://api.github.com/repos/{repo}",
        "title": title,
        "html_url": f"https://github.com/{repo}/pull/{number}",
        "pull_request": {"merged_at": merged_at},
    }


FULL_ROUTES = {
    "/users/": {"login": "octocat", "public_repos": 8},
    "type:pr": {"total_count": 2, "items": [
        pr("2024-05-02T10:00:00Z", "2024-05-02T09:00:00Z", number=1),
        pr("2024-05-03T11:00:00Z", "2024-05-02T09:00:00Z", repo="acme/two", number=2),
    ]},
    "type:issue": {"total_count": 1, "items": [{"title": "bug"}]},
}


def collect(opener, **kwargs):
    kwargs.setdefault("today", scanner.date(2024, 5, 10))
    return scanner.fetch_account("octocat", 30, opener=opener, **kwargs)


# --- collection -------------------------------------------------------------


def test_fetch_account_queries_user_prs_and_issues():
    opener = RecordingOpener(FULL_ROUTES)
    collect(opener)
    assert len(opener.requests) == 3
    assert any("/users/octocat" in url for url in opener.requests)
    assert any("type:pr" in url and "author:octocat" in url for url in opener.requests)
    assert any("type:issue" in url for url in opener.requests)


def test_fetch_account_returns_raw_counts_and_items():
    data = collect(RecordingOpener(FULL_ROUTES))
    assert data["user"]["login"] == "octocat"
    assert data["issues_opened"] == 1
    assert len(data["prs"]) == 2


def test_token_is_sent_as_a_bearer_header_and_never_echoed(monkeypatch):
    seen = {}

    def opener(request, timeout=None):
        seen["auth"] = request.get_header("Authorization")
        return RecordingOpener(FULL_ROUTES)(request, timeout)

    collect(opener, token="s3cr3t-token")
    assert seen["auth"] == "Bearer s3cr3t-token"
    # The token must not leak into any field the CLI can print.
    data = collect(RecordingOpener(FULL_ROUTES), token="s3cr3t-token")
    assert "s3cr3t-token" not in json.dumps(data)


def test_no_token_header_without_a_token():
    captured = {}

    def opener(request, timeout=None):
        captured["auth"] = request.get_header("Authorization")
        return RecordingOpener(FULL_ROUTES)(request, timeout)

    collect(opener, token=None)
    assert captured["auth"] is None


# --- failure modes ----------------------------------------------------------


def test_unknown_user_raises_scan_error():
    opener = RecordingOpener(FULL_ROUTES, error=http_error(404))
    with pytest.raises(scanner.ScanError) as exc:
        collect(opener)
    assert "not found" in str(exc.value).lower()


def test_primary_rate_limit_raises_scan_error_naming_the_token_env_var():
    error = http_error(403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1700000000"})
    with pytest.raises(scanner.ScanError) as exc:
        collect(RecordingOpener(FULL_ROUTES, error=error))
    message = str(exc.value).lower()
    assert "rate limit" in message
    assert "github_token" in message


def test_secondary_rate_limit_raises_scan_error():
    error = http_error(403, {"retry-after": "60"}, body=b'{"message": "secondary rate limit"}')
    with pytest.raises(scanner.ScanError) as exc:
        collect(RecordingOpener(FULL_ROUTES, error=error))
    assert "rate limit" in str(exc.value).lower()


def test_too_many_requests_raises_scan_error():
    with pytest.raises(scanner.ScanError) as exc:
        collect(RecordingOpener(FULL_ROUTES, error=http_error(429)))
    assert "rate limit" in str(exc.value).lower()


def test_network_error_raises_scan_error():
    with pytest.raises(scanner.ScanError) as exc:
        collect(RecordingOpener(FULL_ROUTES, error=urllib.error.URLError("no route to host")))
    assert "network" in str(exc.value).lower()


def test_rate_limit_message_never_contains_the_token():
    error = http_error(403, {"x-ratelimit-remaining": "0"})
    with pytest.raises(scanner.ScanError) as exc:
        collect(RecordingOpener(FULL_ROUTES, error=error), token="s3cr3t-token")
    assert "s3cr3t-token" not in str(exc.value)


# --- analysis ---------------------------------------------------------------


def analyze(prs, issues_opened=0, **kwargs):
    kwargs.setdefault("username", "octocat")
    kwargs.setdefault("days", 30)
    return scanner.analyze(prs, issues_opened, **kwargs)


def test_no_follow_up_signal_fires_without_issues():
    report = analyze([])
    assert report["signals_collected"] == 0


def test_issue_count_is_reported():
    report = analyze([], issues_opened=3)
    assert report["issues_opened"] == 3


def test_signals_collected_counts_prs_not_issues():
    """#23: every signal is PR-derived, so issues opened cannot count toward it."""
    assert analyze([], issues_opened=3)["signals_collected"] == 0
    assert analyze([pr("2024-05-02T10:00:00Z", "2024-05-02T09:00:00Z")],
                   issues_opened=3)["signals_collected"] == 1


def test_volume_burst_fires_above_the_threshold():
    burst = [pr(f"2024-05-02T{h:02d}:00:00Z", "2024-05-02T00:00:00Z", number=h) for h in range(12)]
    report = analyze(burst)
    assert report["max_prs_24h"] == 12
    assert "volume_burst" in [s["name"] for s in report["signals"]]


def test_volume_burst_stays_quiet_at_or_below_the_threshold():
    quiet = [pr(f"2024-05-02T{h:02d}:00:00Z", "2024-05-02T00:00:00Z", number=h) for h in range(10)]
    assert "volume_burst" not in [s["name"] for s in analyze(quiet)["signals"]]


def test_pr_threshold_is_honoured():
    burst = [pr(f"2024-05-02T{h:02d}:00:00Z", "2024-05-02T00:00:00Z", number=h) for h in range(12)]
    report = analyze(burst, pr_threshold=20)
    assert "volume_burst" not in [s["name"] for s in report["signals"]]


def test_trivial_ratio_counts_docs_and_typo_titles():
    mixed = [
        pr("2024-05-02T10:00:00Z", "2024-05-02T09:00:00Z", number=1, title="fix typo in readme"),
        pr("2024-05-02T11:00:00Z", "2024-05-02T09:00:00Z", number=2, title="bump version to 2.0"),
        pr("2024-05-02T12:00:00Z", "2024-05-02T09:00:00Z", number=3, title="rewrite the http client"),
        pr("2024-05-02T13:00:00Z", "2024-05-02T09:00:00Z", number=4, title="add retry budget to fetcher"),
    ]
    report = analyze(mixed)
    assert report["trivial_ratio"] == 0.5
    assert "trivial_fix_ratio" not in [s["name"] for s in report["signals"]]


def test_trivial_ratio_signal_fires_above_the_ratio():
    trivial = [pr("2024-05-02T10:00:00Z", "2024-05-02T09:00:00Z", number=i, title="fix typo")
               for i in range(3)]
    trivial.append(pr("2024-05-02T11:00:00Z", "2024-05-02T09:00:00Z", number=9, title="refactor parser"))
    report = analyze(trivial)
    assert "trivial_fix_ratio" in [s["name"] for s in report["signals"]]


def test_trivial_ratio_needs_at_least_one_sample():
    """A ratio over zero PRs is undefined, not 0.0 that fails the threshold."""
    report = analyze([])
    assert report["trivial_ratio"] is None


def test_cross_repo_dispersion_counts_distinct_repositories():
    prs = [pr(f"2024-05-02T1{h}:00:00Z", "2024-05-02T09:00:00Z", repo=f"acme/r{h}", number=h)
           for h in range(3)]
    prs.append(pr("2024-05-04T10:00:00Z", "2024-05-04T09:00:00Z", repo="acme/r0", number=99))
    assert analyze(prs)["repos_touched"] == 3


def test_shallow_engagement_fires_on_a_fast_merge_median():
    hour = [pr(f"2024-05-02T{h + 10:02d}:00:00Z", f"2024-05-02T{h + 9:02d}:00:00Z", number=h)
            for h in range(3)]
    report = analyze(hour)
    assert report["median_merge_minutes"] == 60
    assert "shallow_engagement" not in [s["name"] for s in report["signals"]]

    merged_at, created_at = "2024-05-02T11:00:00Z", "2024-05-02T10:59:00Z"
    fast = [pr(merged_at, created_at, number=1), pr(merged_at, created_at, number=2)]
    assert "shallow_engagement" in [s["name"] for s in analyze(fast)["signals"]]


def test_score_rises_with_fired_signals_and_stays_in_unit_range():
    nothing = analyze([])
    everything = analyze(
        [pr(f"2024-05-02T{h:02d}:00:00Z", "2024-05-02T09:00:00Z", repo=f"acme/r{h}", number=h, title="fix typo")
         for h in range(20)],
        issues_opened=0,
    )
    assert nothing["score"] == 0.0
    assert 0.0 <= everything["score"] <= 1.0
    assert everything["score"] > nothing["score"]
    assert everything["verdict"] in {"LOW", "MEDIUM", "HIGH"}


def test_report_records_the_window_it_analysed():
    report = analyze([], days=7)
    assert report["days"] == 7
    assert report["username"] == "octocat"


# --- rendering --------------------------------------------------------------


def sample_report():
    return analyze([pr("2024-05-02T10:00:00Z", "2024-05-02T09:59:00Z")], issues_opened=0)


def test_cli_format_is_ascii_only():
    """#20: the report must survive a non-UTF-8 stdout."""
    text = scanner.render(sample_report(), "cli")
    text.encode("ascii")


def test_cli_format_mentions_the_account_and_score():
    text = scanner.render(sample_report(), "cli")
    assert "octocat" in text
    assert "Score" in text


def test_json_format_is_valid_json():
    payload = json.loads(scanner.render(sample_report(), "json"))
    assert payload["username"] == "octocat"
    assert "score" in payload


def test_json_format_never_emits_nan():
    """RFC 8259 has no NaN literal; a null ratio must serialize as null."""
    text = scanner.render(analyze([]), "json")
    assert "NaN" not in text
    assert json.loads(text)["trivial_ratio"] is None


def test_sarif_format_is_a_valid_sarif_log():
    payload = json.loads(scanner.render(sample_report(), "sarif"))
    assert payload["version"] == "2.1.0"
    assert payload["runs"][0]["tool"]["driver"]["name"] == "ai-reputation-guard"
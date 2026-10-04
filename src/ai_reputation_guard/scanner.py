"""Collect GitHub reputation signals and score them.

Three API calls per scan, all through ``urllib.request``: the user record (so an
unknown account fails loudly instead of scoring as empty), merged pull requests
in the window, and issues opened in the window.

The score is a **heuristic**, not a validated model: the weights below are a
first-pass judgement call, not the output of a benchmark. See issue #8.
"""

import json
import re
import statistics
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

API_ROOT = "https://api.github.com"
TIMEOUT = 20
USER_AGENT = "ai-reputation-guard/0.1.0"

# The search API caps at 1000 hits per query, so a very prolific account is
# truncated rather than exhaustively counted.
# ponytail: one page of 100 items, no pagination. Add paging if a scan of a
# >100-PR window matters; the score saturates well before then anyway.
PAGE_SIZE = 100

# Weight per fired signal, chosen to sum to 1.0 across all five. HIGH signals
# (burst volume, trivial fixes) are the documented core of the laundering
# pattern; MEDIUM ones only shift the verdict when something corroborates them.
WEIGHTS = {
    "volume_burst": 0.25,
    "trivial_fix_ratio": 0.25,
    "cross_repo_dispersion": 0.15,
    "shallow_engagement": 0.15,
    "no_follow_up": 0.20,
}

BURST_WINDOW_HOURS = 24
BURST_PR_THRESHOLD = 10
DISPERSION_REPO_THRESHOLD = 15
SHALLOW_MERGE_MINUTES = 5.0
TRIVIAL_RATIO = 0.7

# Title-only heuristic for "mechanically correct, zero engineering value".
# ponytail: matches the PR title, not the diff. Classifying the diff needs one
# extra request per PR; add it when a title stops being good enough.
TRIVIAL_TITLE = re.compile(
    r"\b(docs?|documentation|typo|spelling|whitespace|changelog|readme|"
    r"comment[s]?|format|lint|style|version|bump|dependabot|renovate)\b",
    re.IGNORECASE,
)


class ScanError(RuntimeError):
    """A scan that could not see the account. Always fatal, never exit 0."""


# --- collection -------------------------------------------------------------


def _headers(token):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _get(url, token, opener):
    """One GET, decoded as JSON, with every HTTP/network failure as ScanError."""
    request = urllib.request.Request(url, headers=_headers(token))
    try:
        with opener(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise _scan_error(exc, token) from exc
    except urllib.error.URLError as exc:
        raise ScanError(f"network error talking to the GitHub API: {exc.reason}") from exc
    except (OSError, ValueError) as exc:  # socket timeouts, truncated JSON
        raise ScanError(f"network error talking to the GitHub API: {exc}") from exc


def _scan_error(exc, token=None):
    """Translate an HTTPError into the one message the user needs to act on.

    The token is never part of a message; only the environment variable name is.
    """
    status = exc.code
    if status == 404:
        return ScanError("GitHub user not found; check the username spelling")
    body = b""
    try:
        body = exc.read() or b""
    except Exception:  # a body we cannot read must not mask the status
        pass
    detail = body.decode("utf-8", "replace").lower()
    limited = (
        status == 429
        or (status == 403 and "rate limit" in detail)
        or (status == 403 and exc.headers.get("x-ratelimit-remaining") == "0")
    )
    if limited:
        hint = "the token in GITHUB_TOKEN is exhausted" if token else (
            "set GITHUB_TOKEN to raise it to 5000 requests/hour"
        )
        return ScanError(f"GitHub API rate limit exceeded; {hint}")
    return ScanError(f"GitHub API returned HTTP {status} for the scan request")


def _search(query, token, opener):
    params = urllib.parse.urlencode({"q": query, "per_page": PAGE_SIZE})
    payload = _get(f"{API_ROOT}/search/issues?{params}", token, opener)
    return payload.get("total_count", 0), payload.get("items", [])


def fetch_account(username, days, token=None, opener=urllib.request.urlopen, today=None):
    """Collect raw signal data for ``username`` over the last ``days`` days."""
    since = ((today or date.today()) - timedelta(days=days)).isoformat()
    # The user record is what turns "unknown account" into a clear error instead
    # of an empty-but-successful scan.
    user = _get(f"{API_ROOT}/users/{urllib.parse.quote(username)}", token, opener)
    _, prs = _search(f"type:pr author:{username} is:merged merged:>={since}", token, opener)
    issues_opened, _ = _search(f"type:issue author:{username} created:>={since}", token, opener)
    return {"user": user, "prs": prs, "issues_opened": issues_opened}


# --- analysis ---------------------------------------------------------------


def _parse(ts):
    # GitHub timestamps are UTC ISO-8601 with a trailing Z; timezone-aware is
    # kept so a future non-UTC timestamp cannot silently shift an interval.
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _merged_at(pr):
    return (pr.get("pull_request") or {}).get("merged_at")


def _max_prs_in_window(prs, hours=BURST_WINDOW_HOURS):
    """Largest number of PRs merged inside any sliding window of ``hours``."""
    moments = sorted(filter(None, (_parse(_merged_at(pr)) for pr in prs)))
    if not moments:
        return 0
    best = start = 0
    for end, moment in enumerate(moments):
        while (moment - moments[start]).total_seconds() > hours * 3600:
            start += 1
        best = max(best, end - start + 1)
    return best


def _median_merge_minutes(prs):
    minutes = []
    for pr in prs:
        merged, created = _merged_at(pr), pr.get("created_at")
        if not merged or not created:
            continue
        delta = (_parse(merged) - _parse(created)).total_seconds() / 60
        if delta >= 0:  # a merge cannot precede the PR; a bad record is not a signal
            minutes.append(delta)
    return round(statistics.median(minutes), 1) if minutes else None


def analyze(prs, issues_opened, username="", days=30,
            pr_threshold=BURST_PR_THRESHOLD, trivial_ratio=TRIVIAL_RATIO,
            dispersion_threshold=DISPERSION_REPO_THRESHOLD,
            shallow_minutes=SHALLOW_MERGE_MINUTES):
    """Turn collected data into signals, a score and a verdict."""
    total = len(prs)
    trivial = sum(1 for pr in prs if TRIVIAL_TITLE.search(pr.get("title") or ""))
    trivial_share = round(trivial / total, 2) if total else None
    # repository_url is https://api.github.com/repos/<owner>/<name>.
    repo_names = {"/".join((pr.get("repository_url") or "").split("/")[-2:]) for pr in prs}
    median_minutes = _median_merge_minutes(prs)
    max_burst = _max_prs_in_window(prs)

    signals = []
    if max_burst > pr_threshold:
        signals.append({
            "name": "volume_burst",
            "detail": f"{max_burst} PRs merged inside {BURST_WINDOW_HOURS}h "
                      f"(threshold {pr_threshold})",
        })
    # Guarded on `total`: a ratio over zero PRs is undefined, and calling that
    # 0.0 would silently fire the opposite way on the weakest possible data.
    if trivial_share is not None and trivial_share > trivial_ratio:
        signals.append({
            "name": "trivial_fix_ratio",
            "detail": f"{trivial}/{total} merged PRs look like docs/typo-only changes "
                      f"(ratio {trivial_share} > {trivial_ratio})",
        })
    if len(repo_names) > dispersion_threshold:
        signals.append({
            "name": "cross_repo_dispersion",
            "detail": f"{len(repo_names)} distinct repositories in {days} days "
                      f"(threshold {dispersion_threshold})",
        })
    if median_minutes is not None and median_minutes < shallow_minutes:
        signals.append({
            "name": "shallow_engagement",
            "detail": f"median PR lifespan {median_minutes}min "
                      f"(threshold {shallow_minutes}min)",
        })
    # Only meaningful when the account actually merged something: zero issues
    # after zero PRs is absence of data, not absence of engagement.
    if total and not issues_opened:
        signals.append({
            "name": "no_follow_up",
            "detail": f"0 issues opened in {days} days",
        })

    score = round(min(1.0, sum(WEIGHTS[s["name"]] for s in signals)), 2)
    return {
        "username": username,
        "days": days,
        "pr_count": total,
        "trivial_ratio": trivial_share,
        "max_prs_24h": max_burst,
        "repos_touched": len(repo_names),
        "median_merge_minutes": median_minutes,
        "issues_opened": issues_opened,
        # 0 here means the scan saw nothing at all, which the CLI reports as a
        # failure rather than a clean bill of health.
        "signals_collected": total + issues_opened,
        "signals": signals,
        "score": score,
        "verdict": "HIGH" if score >= 0.6 else "MEDIUM" if score >= 0.3 else "LOW",
    }


# --- rendering --------------------------------------------------------------


def _format_ratio(value):
    return "n/a" if value is None else f"{value:.2f}"


def render(report, fmt):
    if fmt == "json":
        return json.dumps(report, indent=2, sort_keys=True, allow_nan=False)
    if fmt == "sarif":
        return json.dumps(_sarif(report), indent=2, sort_keys=True, allow_nan=False)
    return _render_cli(report)


def _render_cli(report):
    # ASCII only: a literal em-dash here raised UnicodeEncodeError under any
    # non-UTF-8 stdout, so `scan` exited 1 where `--help` succeeded (#20).
    lines = [
        f"Account:        {report['username']}",
        f"Window:         last {report['days']} days",
        f"Score:          {report['score']:.2f} ({report['verdict']})",
        f"Merged PRs:     {report['pr_count']}",
        f"Trivial ratio:  {_format_ratio(report['trivial_ratio'])}",
        f"Burst max 24h:  {report['max_prs_24h']}",
        f"Repos touched:  {report['repos_touched']}",
        f"Median merge:   {_format_ratio(report['median_merge_minutes'])} min",
        f"Issues opened:  {report['issues_opened']}",
    ]
    if report["signals"]:
        lines.append("Signals:")
        lines.extend(f"  - {s['name']}: {s['detail']}" for s in report["signals"])
    else:
        lines.append("Signals:        none")
    lines.append("Note:           heuristic score, not a validated model (see issue #8)")
    return "\n".join(lines)


SARIF_LEVEL = {"HIGH": "error", "MEDIUM": "warning", "LOW": "note"}


def _sarif(report):
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {
                "name": "ai-reputation-guard",
                "informationUri": "https://github.com/yunaremaia/ai-reputation-guard",
                "rules": [{
                    "id": signal["name"],
                    "shortDescription": {"text": signal["detail"]},
                } for signal in report["signals"]],
            }},
            "results": [{
                "ruleId": signal["name"],
                "level": SARIF_LEVEL[report["verdict"]],
                "message": {"text": signal["detail"]},
            } for signal in report["signals"]],
        }],
    }
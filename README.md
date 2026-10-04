# AI Reputation Guard

[![CI](https://github.com/yunaremaia/ai-reputation-guard/actions/workflows/ci.yml/badge.svg)](https://github.com/yunaremaia/ai-reputation-guard/actions/workflows/ci.yml)

> Detect AI-assisted reputation laundering on GitHub — scan accounts for high-volume trivial PR patterns, timing heuristics, and cross-repo attribution signals that indicate gaming of OSS reputation systems.

## Problem

GitHub profile READMEs, contribution graphs, and "X merged PRs" metrics are increasingly gamed. The pattern is well-documented:

- An account opens 20+ trivial PRs in a single day across different repos
- PRs are single-line doc fixes, typo corrections, version bumps — mechanically correct but zero engineering value
- Purpose: inflate contribution counts, build fake OSS credibility, then monetize via consulting, grants, or social capital

Existing tools (`codeassay`, `ghostwrite`, `ai-authorship`) detect **AI-authored commits** — they tell you *what* was written by AI. They do not answer the harder question: *is this account gaming the reputation system?*

`ai-reputation-guard` fills that gap. It answers: **does this account's contribution pattern look laundered?**

## What It Detects

These are the signals `scan` collects today, from three GitHub REST calls: the
user record, merged pull requests in the window (`type:pr ... is:merged`), and
issues opened in the window (`type:issue ... created:`).

| Signal | Source | Fires when | Weight |
|--------|--------|-----------|--------|
| `volume_burst` | merged PR timestamps | > `--pr-threshold` (default 10) PRs merged inside any 24h window | 0.25 |
| `trivial_fix_ratio` | PR titles | share of merged PRs whose title matches a docs/typo/whitespace/changelog/version-bump pattern > `--trivial-ratio` (default 0.7) | 0.25 |
| `cross_repo_dispersion` | PR repository URLs | > 15 distinct repositories in the window | 0.15 |
| `shallow_engagement` | PR created/merged timestamps | median open→merge time < 5 minutes | 0.15 |
| `no_follow_up` | issue search | 0 issues opened, with at least one merged PR in the window | 0.20 |

The score is the sum of the weights that fired, clamped to 1.0, and the verdict
is `HIGH` at 0.6+, `MEDIUM` at 0.3+, `LOW` below.

**The score is a heuristic, not a validated model.** The weights are a
first-pass judgement call; there is no benchmark behind them yet
(tracked in [#8](https://github.com/yunaremaia/ai-reputation-guard/issues/8)).
Treat a HIGH score as "worth a human look", never as a verdict on a person.

Known limits of the current implementation:

- Triviality is classified from the PR title only, not the diff. Classifying
  diffs costs one extra API request per PR.
- The search API returns at most 100 items per query, so a window with more than
  100 merged PRs is truncated at 100.
- Issue *comments*, reviews and discussions are not collected; "no follow-up"
  counts issues opened only.

## Install

```bash
pip install git+https://github.com/yunaremaia/ai-reputation-guard.git
```

## Authentication

Unauthenticated requests work but are limited to 10 search requests per minute
and are shared across everyone behind the IP. Set a token for anything real:

```bash
export GITHUB_TOKEN=ghp_...   # or GH_TOKEN; used for auth only, never printed
```

## Usage

```bash
# Scan a single account
ai-reputation-guard scan yunaremaia

# Scan with custom thresholds
ai-reputation-guard scan someuser --pr-threshold 15 --trivial-ratio 0.6

# Output JSON for CI (writes the report to the file; nothing else is printed)
ai-reputation-guard scan someuser --format json --output report.json

# Batch scan (for org security teams)
ai-reputation-guard batch --members-file members.txt --format sarif --output guard.sarif
```

## Sample Output

```
$ ai-reputation-guard scan yunaremaia
Account:        yunaremaia
Window:         last 30 days
Score:          0.40 (MEDIUM)
Merged PRs:     100
Trivial ratio:  0.26
Burst max 24h:  74
Repos touched:  26
Median merge:   7.00 min
Issues opened:  2626
Signals:
  - volume_burst: 74 PRs merged inside 24h (threshold 10)
  - cross_repo_dispersion: 26 distinct repositories in 30 days (threshold 15)
Note:           heuristic score, not a validated model (see issue #8)
```

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | scan completed and a report was produced |
| 1 | the scan failed (unknown user, rate limit, network error, unwritable `--output`) or collected nothing at all |
| 2 | bad command line |

`scan` never exits 0 without a report: a failed call and a window with zero
merged PRs and zero issues are both errors, because a CI gate that treats them
as success is worse than no gate.

## Architecture

```
ai_reputation_guard/
├── scanner.py    # API client, signal collection, scoring, rendering
└── cli.py        # argparse surface, exit codes, --output
```

Splitting `scanner.py` into `signals/`, `scoring.py` and `formatters.py` is
tracked in [#7](https://github.com/yunaremaia/ai-reputation-guard/issues/7); it
is one module today because there is one signal set and one scorer.

## Tests

```bash
pip install -e . pytest
pytest tests/
```

The suite never touches the network: the GitHub API is injected at
`scanner.fetch_account` and at the `opener` seam, so every rate-limit, 404 and
socket-error path is exercised deterministically.

## Roadmap

- [x] SARIF output for Code Scanning tab
- [ ] `batch` scanning (`batch` is still a stub, #7)
- [ ] Mechanical-timing signal (PRs opened at regular intervals)
- [ ] Diff-level triviality classification
- [ ] Result caching and rate-limit budgeting (#6)
- [ ] Benchmark the scoring weights against labelled accounts (#8)
- [ ] GitHub Action integration (scan on new contributor)
- [ ] Sliding-window trend detection (sudden volume spikes)
- [ ] Baseline mode (suppress known-good accounts)
- [ ] Cross-account clustering (sock puppet detection)
- [ ] MCP server for agent-tool integration

## License

MIT

## Contributing

PRs welcome. Adding a signal means one entry in `scanner.WEIGHTS`, one rule in
`scanner.analyze`, and a test in `tests/test_scanner.py` that both fires and
stays quiet.

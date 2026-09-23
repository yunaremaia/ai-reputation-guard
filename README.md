# AI Reputation Guard

> Detect AI-assisted reputation laundering on GitHub — scan accounts for high-volume trivial PR patterns, timing heuristics, and cross-repo attribution signals that indicate gaming of OSS reputation systems.

## Problem

GitHub profile READMEs, contribution graphs, and "X merged PRs" metrics are increasingly gamed. The pattern is well-documented:

- An account opens 20+ trivial PRs in a single day across different repos
- PRs are single-line doc fixes, typo corrections, version bumps — mechanically correct but zero engineering value
- Purpose: inflate contribution counts, build fake OSS credibility, then monetize via consulting, grants, or social capital

Existing tools (`codeassay`, `ghostwrite`, `ai-authorship`) detect **AI-authored commits** — they tell you *what* was written by AI. They do not answer the harder question: *is this account gaming the reputation system?*

`ai-reputation-guard` fills that gap. It answers: **does this account's contribution pattern look laundered?**

## What It Detects

| Signal | Description | Weight |
|--------|-------------|--------|
| **Volume burst** | >10 merged PRs within 24h window | HIGH |
| **Trivial fix ratio** | >70% of PRs are docs/typo/whitespace-only | HIGH |
| **Shallow engagement** | Median PR lifespan < 5min (open → merge) | MEDIUM |
| **Cross-repo dispersion** | >15 distinct repos touched in 7 days | MEDIUM |
| **No follow-up** | 0 issues opened, 0 discussions participated | MEDIUM |
| **Mechanical timing** | PRs opened at regular 30-60min intervals | LOW |

## Install

```bash
pip install git+https://github.com/yunaremaia/ai-reputation-guard.git
```

## Usage

```bash
# Scan a single account
ai-reputation-guard scan yunaremaia

# Scan with custom thresholds
ai-reputation-guard scan someuser --pr-threshold 15 --trivial-ratio 0.6

# Output JSON for CI
ai-reputation-guard scan someuser --format json --output report.json

# Batch scan (for org security teams)
ai-reputation-guard batch --members-file members.txt --format sarif --output guard.sarif
```

## Sample Output

```
Account:        someuser
Score:          0.82 (HIGH — likely laundered)
Total PRs:      47 (last 30 days)
Trivial ratio:  0.89
Burst windows:  3 (max 12 PRs in 24h)
Repos touched:  31
Issues opened:  0
Verdict:        Pattern consistent with reputation gaming
```

## Architecture

```
ai_reputation_guard/
├── scanner.py          # GitHub API client, PR fetcher
├── signals/
│   ├── volume.py       # Burst detection, rate analysis
│   ├── triviality.py   # Diff classification (docs/typo/code)
│   ├── timing.py       # Interval regularity, session detection
│   └── engagement.py   # Issues, reviews, discussions
├── scoring.py          # Weighted risk score → verdict
├── formatters.py       # CLI / JSON / SARIF output
└── cli.py              # Entry point
```

## Roadmap

- [ ] GitHub Action integration (scan on new contributor)
- [ ] SARIF output for Code Scanning tab
- [ ] Baseline mode (suppress known-good accounts)
- [ ] Sliding-window trend detection (sudden volume spikes)
- [ ] Cross-account clustering (sock puppet detection)
- [ ] MCP server for agent-tool integration

## License

MIT

## Contributing

PRs welcome. See CONTRIBUTING.md for the signal taxonomy and how to add new detectors.

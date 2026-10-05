# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-10-05

First release. `scan` queries the GitHub API for real data and scores five
reputation-laundering signals; `batch` is still a stub (#7).

### Added

- `scan <username>` collects three signals' worth of data with three GitHub REST
  calls: the user record, merged pull requests in the window
  (`type:pr ... is:merged`), and issues opened in the window
  (`type:issue ... created:`).
- Five signals, each weighted and each with a test that both fires and stays
  quiet: `volume_burst` (0.25), `trivial_fix_ratio` (0.25),
  `cross_repo_dispersion` (0.15), `shallow_engagement` (0.15) and
  `no_follow_up` (0.20). The score is the sum of the fired weights clamped to
  1.0; the verdict is `HIGH` at 0.6+, `MEDIUM` at 0.3+, `LOW` below.
- `--format sarif` output for the Code Scanning tab (#19).
- `--output <path>` writes the report and creates missing parent directories;
  a report is no longer parsed and discarded.
- `GITHUB_TOKEN` / `GH_TOKEN` authentication. The token is used for auth only
  and is never printed.
- GitHub Actions workflow running the suite, plus a CI badge in the README.
- `SECURITY.md` with vulnerability reporting guidelines.
- MIT license.

### Fixed

- `scan` printed "implement scanner logic next" and exited 0, so every CI gate
  built on it passed while nothing was ever scanned (#21).
- An unwritable `--output` path exited 0 and left a stale report behind; a
  failed scan and a window that collected nothing now both exit 1 (#19).
- The CLI output contained a literal em-dash that raised
  `UnicodeEncodeError` under any non-UTF-8 stdout, crashing with exit 1 where
  `--help` succeeded. All output is ASCII now (#20).
- `--pr-threshold`, `--days` and `--trivial-ratio` accepted out-of-domain values
  (`nan`, `inf`, `0`, negatives, a ratio above 1.0) with exit 0. `nan` silently
  disabled every comparison against it, so a signal that should fire never
  did, and `json.dumps` emitted bare `NaN`, which is not valid JSON per
  RFC 8259. The domain is now enforced at the parser (#13).
- `find_packages()` installed a top-level `src` package into site-packages,
  colliding with any other src-layout project (#11).
- `tests/conftest.py` pinned `tests/` instead of the repo root, so the suite only
  imported when the package was already installed (#12).
- CI matrix skipped Python 3.10, which `python_requires` claimed to support
  (#15).

### Changed

- The package is namespaced under `src/ai_reputation_guard/`. Bare
  `find_packages()` shipped `src` itself and installed a top-level `src` into
  site-packages (#11).
- Dropped the unused `click` and `requests` runtime dependencies; the CLI is
  stdlib `argparse` and the scanner is stdlib `urllib.request`, so nothing is
  needed from PyPI (#14).
- CI now tests every version the manifest claims to support, 3.9 through 3.14,
  and `python_requires` is pinned to `>=3.9,<3.15` so the claim stops implying
  support for every future release nobody has looked at (#15).
- The scoring weights are documented in the README as a heuristic with no
  benchmark behind them yet, so a `HIGH` score reads as "worth a human look"
  rather than a verdict on a person.

### Known issues

Fixed in a later release; listed here so the notes do not overstate 0.1.0.

- An account with zero merged PRs but some issues opened reports `0.00 (LOW)`
  and exits 0, because all five signals are PR-derived (#23).
- `--days` has no upper bound, so a very large window escapes as an unhandled
  `OverflowError` traceback and exit 1 instead of a parser error (#22).
- `batch` parses its arguments and exits 0 without scanning anything or
  writing `--output` (#7).

[0.1.0]: https://github.com/yunaremaia/ai-reputation-guard/releases/tag/v0.1.0
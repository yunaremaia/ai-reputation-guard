"""CI/manifest agreement tests.

`python_requires` and the CI matrix are two hand-maintained statements of the
same fact — which Python versions this project supports — and nothing checked
that they agreed. The matrix was `3.9, 3.11, 3.12, 3.13` while the manifest
claimed `>=3.9`: Python 3.10 was declared-supported and never exercised by CI
or by a test (#15).

The metadata is read from ``setup.py``; when the packaging metadata moves to
``pyproject.toml`` (#5), this reader has to move with it.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SETUP_PY = REPO_ROOT / "setup.py"
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"

# (floor, ceiling) as version tuples. The ceiling is exclusive.
EXPECTED_FLOOR = (3, 9)
EXPECTED_CEILING = (3, 15)


def _version_tuple(text):
    return tuple(int(part) for part in text.strip().split("."))


def _version_range(floor, ceiling):
    """Every ``x.y`` in ``[floor, ceiling)``, oldest first."""
    return [
        (major, minor)
        for major in range(floor[0], ceiling[0] + 1)
        for minor in range(0 if major > floor[0] else floor[1], 100)
        if floor <= (major, minor) < ceiling
    ]


def _declared_python_requires():
    """Parse ``python_requires`` out of setup.py, returning its raw text."""
    match = re.search(
        r"""python_requires\s*=\s*(?P<q>['"])(?P<spec>[^'"]+)(?P=q)""", SETUP_PY.read_text()
    )
    assert match, "setup.py does not declare python_requires"
    return match.group("spec")


def _declared_range():
    """The declared support range as ``(floor, ceiling)`` version tuples.

    Fails when there is no upper bound: an open-ended ``>=3.9`` silently claims
    support for every future release, including versions nobody has looked at
    and that may not even exist yet.
    """
    spec = _declared_python_requires()
    lower = re.search(r">=\s*([\d.]+)", spec)
    upper = re.search(r"<\s*([\d.]+)", spec)
    assert lower, f"python_requires={spec!r} must declare a lower bound like '>=3.9'"
    assert upper, (
        f"python_requires={spec!r} has no upper bound, so it claims support for "
        "every future Python release. Declare an explicit ceiling (for example "
        "'>=3.9,<3.15') so the manifest and the CI matrix can be checked against "
        "each other, and bump it when a newer release is actually tested."
    )
    return _version_tuple(lower.group(1)), _version_tuple(upper.group(1))


def _ci_matrix():
    """The ``python-version`` matrix from the CI workflow, as version tuples."""
    match = re.search(r"python-version:\s*\[(?P<body>[^\]]*)\]", CI_YML.read_text())
    assert match, f"no python-version matrix found in {CI_YML}"
    versions = re.findall(r"[\d]+\.[\d]+", match.group("body"))
    assert versions, "the python-version matrix is empty"
    return [_version_tuple(v) for v in versions]


# --- the manifest must state a checkable claim -------------------------------


def test_python_requires_declares_an_upper_bound():
    """Without a ceiling, the manifest claims support for 3.15, 3.16 and every
    release after, none of which has been tested by anything."""
    floor, ceiling = _declared_range()
    assert floor < ceiling, f"empty support range: >={floor} <{ceiling}"


# --- the CI matrix must match that claim -------------------------------------


def test_ci_matrix_covers_every_declared_python_version():
    """The drift from #15: 3.10 was in the manifest's range and absent from the
    matrix, so a declared-supported version was never exercised."""
    floor, ceiling = _declared_range()
    declared = _version_range(floor, ceiling)
    matrix = _ci_matrix()

    missing = [v for v in declared if v not in matrix]
    assert not missing, (
        f"CI matrix {['.'.join(map(str, v)) for v in matrix]} does not cover "
        f"declared-supported Python "
        f"{['.'.join(map(str, v)) for v in missing]} (from "
        f"python_requires >={'.'.join(map(str, floor))},"
        f"<{'.'.join(map(str, ceiling))}). Every version the manifest claims "
        "must be exercised by CI."
    )

    extra = [v for v in matrix if v not in declared]
    assert not extra, (
        f"CI matrix tests Python {['.'.join(map(str, v)) for v in extra]}, which "
        f"python_requires >={'.'.join(map(str, floor))},"
        f"<{'.'.join(map(str, ceiling))} does not claim. Either widen the "
        "manifest or drop the leg."
    )


def test_ci_matrix_tests_the_declared_floor():
    """The minimum supported version is the one most likely to break, because
    nothing enforces newer-only syntax at review time."""
    floor, _ = _declared_range()
    assert floor in _ci_matrix(), (
        f"CI never tests the declared minimum Python {'.'.join(map(str, floor))}"
    )


def test_every_ci_matrix_version_satisfies_the_declared_range():
    """Each leg must actually be allowed by the manifest it is testing."""
    floor, ceiling = _declared_range()
    outside = [v for v in _ci_matrix() if not floor <= v < ceiling]
    assert not outside, (
        f"CI tests {['.'.join(map(str, v)) for v in outside]}, outside the "
        f"declared range [>={'.'.join(map(str, floor))},"
        f"<{'.'.join(map(str, ceiling))})"
    )


def test_declared_range_is_contiguous_with_no_untested_gap():
    """A hand-maintained list is easy to transcribe with a hole in it; assert the
    matrix is a contiguous run so a future edit cannot reintroduce one."""
    matrix = _ci_matrix()
    expected = _version_range(matrix[0], (matrix[-1][0], matrix[-1][1] + 1))
    assert matrix == expected, (
        f"CI matrix {['.'.join(map(str, v)) for v in matrix]} is not contiguous; "
        f"expected {['.'.join(map(str, v)) for v in expected]}"
    )


# --- pinning today's declared support ---------------------------------------


def test_declared_support_range_is_what_this_project_intends():
    """Pins the current contract so a silent widening or narrowing is visible in
    the diff, whichever direction it moves."""
    floor, ceiling = _declared_range()
    assert (floor, ceiling) == (EXPECTED_FLOOR, EXPECTED_CEILING), (
        f"declared support range changed from >={EXPECTED_FLOOR},<{EXPECTED_CEILING} "
        f"to >={floor},<{ceiling}; update this test deliberately when the supported "
        "range changes, and add the matching legs to the CI matrix."
    )
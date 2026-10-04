"""Packaging and dependency-manifest tests.

These pin three properties of the distribution that the test suite cannot
otherwise observe, because a green suite does not tell you what an install
puts into site-packages:

  - the installed top-level package is namespaced, not a generic ``src``
    (#11) — two src-layout projects in one environment would otherwise
    collide on the same directory name;
  - the suite imports without relying on the caller's cwd (#12) — a
    no-op conftest guard hides behind ``python -m pytest``, which silently
    injects the cwd;
  - every declared runtime dependency is actually imported, and vice versa
    (#14) — declared-but-unimported deps are invisible to pytest and drag in
    transitive install-time surface for code that never uses them.

The wheel is built in a throwaway copy of the source tree: building in place
would drop ``build/`` and ``*.egg-info/`` into the repository.
"""

import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
import sysconfig
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
PACKAGE_NAME = "ai_reputation_guard"

# Import names that must never appear as a top-level installed package.
# `src` is the collision from #11; the others are a generic layout marker.
FORBIDDEN_TOP_LEVEL = frozenset({"src", "tests", "test", "test_cli"})


def _build_wheel(tmp_path):
    """Build a wheel from a copy of the repo; return the wheel's path."""
    src_copy = tmp_path / "src-copy"
    src_copy.mkdir()
    for name in ("setup.py", "README.md", "LICENSE"):
        origin = REPO_ROOT / name
        if origin.exists():
            (src_copy / name).write_bytes(origin.read_bytes())
    (src_copy / "src").symlink_to(SRC_DIR, target_is_directory=True)

    out = tmp_path / "dist"
    out.mkdir()
    subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys;from setuptools import build_meta as b;"
                "print(b.build_wheel(sys.argv[1]))"
            ),
            str(out),
        ],
        cwd=src_copy,
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = list(out.glob("*.whl"))
    assert len(wheels) == 1, f"expected exactly one wheel, got {wheels}"
    return wheels[0]


def _setup_py_kwargs():
    """Return the keyword arguments ``setup.py`` passes to ``setuptools.setup``."""
    script = (
        "import json, runpy, sys\n"
        "from unittest import mock\n"
        "captured = {}\n"
        "with mock.patch('setuptools.setup', lambda **kw: captured.update(kw)):\n"
        "    runpy.run_path('setup.py', run_name='__not_main__')\n"
        "sys.stdout.write(json.dumps(captured, default=str))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(proc.stdout)


def _third_party_imports(paths):
    """Top-level module names imported by ``paths``, minus the stdlib.

    A declared dependency that is never imported pulls in a transitive tree for
    nothing, so this deliberately walks the AST rather than importing anything.
    """
    stdlib_roots = {
        sysconfig.get_paths().get("stdlib"),
        sysconfig.get_paths().get("platstdlib"),
    }

    def is_stdlib(name):
        if name in sys.builtin_module_names:
            return True
        try:
            spec = importlib.util.find_spec(name)
        except (ImportError, ValueError):
            return False
        if spec is None:
            return True
        origin = spec.origin
        if origin in (None, "built-in", "frozen"):
            return True
        return any(origin.startswith(root) for root in stdlib_roots if root)

    found = set()
    for path in paths:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
    # The package's own modules are local, not third-party.
    return {name for name in found if not is_stdlib(name) and name != PACKAGE_NAME}


def _requirement_name(requirement):
    """The import name a requirement string provides ('click>=8.0' -> 'click')."""
    return (
        requirement.split(";")[0]
        .strip()
        .split("[")[0]
        .split(">")[0]
        .split("<")[0]
        .split("=")[0]
        .split("!")[0]
        .split("~")[0]
        .strip()
        .replace("-", "_")
    )


# --- #11: the installed top-level package is namespaced ----------------------


def test_wheel_does_not_install_a_generic_top_level_package(tmp_path):
    """Regression for #11: `find_packages()` shipped a top-level `src`.

    Every other src-layout project creates the same directory name, so whichever
    installs second overwrites or namespace-shares the first, and `import
    src.<anything>` becomes ambiguous across unrelated projects.
    """
    wheel = _build_wheel(tmp_path)
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        top_level_entry = next(n for n in names if n.endswith("top_level.txt"))
        top_level = {
            line.strip() for line in archive.read(top_level_entry).decode().splitlines()
        }

    assert top_level == {PACKAGE_NAME}, (
        f"wheel declares top-level package(s) {sorted(top_level)}, "
        f"expected exactly {{{PACKAGE_NAME!r}}}"
    )
    assert not (top_level & FORBIDDEN_TOP_LEVEL), (
        f"wheel installs generic top-level package(s) {sorted(top_level & FORBIDDEN_TOP_LEVEL)}; "
        "these collide with any other src-layout project in the same environment"
    )


def test_wheel_ships_the_package_as_a_named_import_path(tmp_path):
    """The import path must be `ai_reputation_guard/...`, not `src/...`."""
    wheel = _build_wheel(tmp_path)
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())

    shipped = {n for n in names if n.endswith(".py") and not n.startswith(f"{PACKAGE_NAME}.dist-info")}
    assert shipped == {f"{PACKAGE_NAME}/__init__.py", f"{PACKAGE_NAME}/cli.py"}, (
        f"unexpected shipped modules: {sorted(shipped)}"
    )


def test_package_is_importable_under_its_namespaced_name(tmp_path):
    """The namespaced package must import from the built wheel's layout."""
    wheel = _build_wheel(tmp_path)
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(tmp_path / "unpacked")

    script = f"import {PACKAGE_NAME}, {PACKAGE_NAME}.cli;print({PACKAGE_NAME}.__version__)"
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path / "unpacked",
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(tmp_path / "unpacked")},
    )
    assert proc.returncode == 0, f"importing {PACKAGE_NAME} failed:\n{proc.stderr}"
    assert proc.stdout.strip(), f"{PACKAGE_NAME}.__version__ was empty"


def test_console_entry_point_targets_the_namespaced_module():
    """`ai-reputation-guard=src.cli:main` only resolves while nothing else
    displaces a top-level `src` (#11)."""
    kwargs = _setup_py_kwargs()
    scripts = kwargs["entry_points"]["console_scripts"]
    assert scripts == [f"ai-reputation-guard={PACKAGE_NAME}.cli:main"], (
        f"console_scripts should target the namespaced module, got {scripts}"
    )


# --- #12: the suite does not depend on the caller's cwd -----------------------


def test_conftest_guard_makes_the_package_importable():
    """Regression for #12: the conftest sys.path guard was a no-op.

    `ROOT = Path(__file__).resolve().parent` resolves to `tests/`, not the
    repository root, so the guard contributed nothing and the suite only
    imported because `python -m pytest` implicitly prepends the cwd.

    This asserts the guard's actual contract — *the directory it pins must be
    one the package can be imported from* — rather than a particular spelling
    of the path expression. Under a `src/` layout that directory is `src/`, not
    the repository root, so a test hardcoding `.parent.parent` would encode the
    wrong requirement.
    """
    # Execute conftest the way pytest would, from an unrelated cwd, then try to
    # import the package it was supposed to make available.
    script = (
        "import runpy, sys\n"
        "runpy.run_path(r'{conftest}')\n"
        "import {pkg}\n"
        "print({pkg}.__file__)\n"
    ).format(conftest=REPO_ROOT / "tests" / "conftest.py", pkg=PACKAGE_NAME)

    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tempfile.gettempdir(),
        check=False,
        capture_output=True,
        text=True,
        env={
            k: v
            for k, v in os.environ.items()
            if k not in ("PYTHONPATH", "PYTHONHOME")
        },
    )
    assert proc.returncode == 0, (
        f"after running tests/conftest.py, `import {PACKAGE_NAME}` still failed — "
        f"the sys.path guard is not pinning a directory the package can be "
        f"imported from.\n{proc.stderr[-2000:]}"
    )
    resolved = Path(proc.stdout.strip()).resolve()
    assert resolved.is_relative_to(REPO_ROOT), (
        f"{PACKAGE_NAME} was imported from {resolved}, which is outside the repository; "
        "the suite would be testing an installed copy instead of this checkout"
    )


def test_suite_collects_from_an_unrelated_cwd_without_the_package_installed(tmp_path):
    """Run the suite from a directory that is not the repo, with no editable
    install on sys.path, so only conftest can make the imports resolve.

    This is the reproduction from #12: on `main` the `pytest` console script
    dies with `ModuleNotFoundError: No module named 'src'`, exit code 2.
    """
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(REPO_ROOT / "tests"),
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=tmp_path,  # deliberately NOT the repository
        check=False,
        capture_output=True,
        text=True,
        env={
            k: v
            for k, v in os.environ.items()
            if k not in ("PYTHONPATH", "PYTHONHOME")
        },
    )
    assert proc.returncode == 0, (
        "collecting the suite from an unrelated cwd failed; the conftest guard "
        f"is not making the package importable.\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
    )
    # Collection succeeded and found real tests. Assert on the collected count
    # rather than grepping for "error": several passing test names contain it,
    # and `-q --collect-only` prints no session header.
    assert re.search(r"\b[1-9]\d* tests? collected\b", proc.stdout), (
        f"expected the suite to collect tests, got:\n{proc.stdout[-2000:]}"
    )


# --- #14: declared dependencies match actual imports -------------------------


def test_declared_dependencies_are_all_imported_by_the_package():
    """Regression for #14: `click` and `requests` were declared but never imported.

    The CLI is built on stdlib `argparse`, so every install pulled in two
    dependency trees — one of them five packages of transitive surface — for
    code that makes no network calls at all.
    """
    kwargs = _setup_py_kwargs()
    declared = {_requirement_name(r) for r in kwargs["install_requires"]}
    imported = _third_party_imports(sorted(SRC_DIR.rglob("*.py")))

    unused = declared - imported
    assert not unused, (
        f"install_requires declares {sorted(unused)} but nothing under src/ imports "
        f"them (src/ imports: {sorted(imported)}). Remove them, or import them for real."
    )


def test_imported_third_party_modules_are_all_declared():
    """The converse drift: an import with no matching requirement, which only
    fails at runtime on someone else's machine."""
    kwargs = _setup_py_kwargs()
    declared = {_requirement_name(r) for r in kwargs["install_requires"]}
    imported = _third_party_imports(sorted(SRC_DIR.rglob("*.py")))

    undeclared = imported - declared
    assert not undeclared, (
        f"src/ imports {sorted(undeclared)} but install_requires declares {sorted(declared)}. "
        "Add the missing requirement."
    )


def test_cli_does_not_depend_on_a_second_cli_framework():
    """`cli.py` is built on stdlib `argparse` and should stay that way; a
    second CLI framework would be a deliberate choice, not an accident."""
    imported = _third_party_imports([SRC_DIR / PACKAGE_NAME / "cli.py"])
    assert "click" not in imported, (
        "cli.py must not import click alongside argparse; pick one CLI framework"
    )
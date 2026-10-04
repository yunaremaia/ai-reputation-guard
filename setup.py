from setuptools import setup, find_packages

setup(
    name="ai-reputation-guard",
    version="0.1.0",
    # The package is `src/ai_reputation_guard/`, not `src/`. Bare
    # `find_packages()` treated `src/` itself as a package and installed a
    # top-level `src` into site-packages, where it collides with every other
    # src-layout project in the same environment (#11).
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    # The CLI is stdlib argparse and the scanner is stdlib urllib.request, so
    # it needs nothing from PyPI. The project deliberately dropped its unused
    # dependencies in #17; do not add one back without a caller for it.
    install_requires=[],
    entry_points={
        "console_scripts": [
            "ai-reputation-guard=ai_reputation_guard.cli:main",
        ],
    },
    python_requires=">=3.9,<3.15",
    author="Yunare Maia",
    description="Detect AI-assisted reputation laundering on GitHub",
    license="MIT",
)

"""Pytest bootstrap.

Issue #11 tracks the packaging flaw where ``find_packages()`` installs ``src``
as a top-level package. Pinning the repository root on ``sys.path`` keeps the
suite importable regardless of how the package was installed, so CI fails on a
real regression instead of an import error.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
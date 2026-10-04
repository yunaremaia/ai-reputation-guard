"""Pytest bootstrap.

Pins the package's import root on ``sys.path`` so the suite runs straight from
a checkout, with no install step, and so CI exercises that same path instead of
relying on ``python -m pytest`` to implicitly prepend the cwd.

This guard used to be a no-op: it resolved ``Path(__file__).resolve().parent``,
which is ``tests/`` — a directory the package cannot be imported from. The
suite therefore only passed because it was either installed or run with ``-m``
(see #12).
"""

import sys
from pathlib import Path

# The import root is `src/`, because the package lives at
# `src/ai_reputation_guard/`. Pinning the repository root instead would be no
# better than pinning `tests/`: neither contains the package.
IMPORT_ROOT = Path(__file__).resolve().parent.parent / "src"

if str(IMPORT_ROOT) not in sys.path:
    sys.path.insert(0, str(IMPORT_ROOT))
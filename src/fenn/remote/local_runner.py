"""Local execution branch for ``fenn run`` (used when no ``--host`` is set).

This is intentionally a thin wrapper around :func:`runpy.run_path`. It
preserves the user's existing mental model: ``fenn run main.py`` should behave
exactly as ``python main.py`` does today, including the singleton lifecycle
of :class:`fenn.logging.Logger` and friends.
"""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


def run_local(script: Path) -> None:
    """Execute ``script`` as if it were invoked with ``python <script>``.

    Sets ``sys.argv[0]`` to the script path, sets ``__name__`` to ``__main__``,
    and chdirs to the script's parent so ``fenn.yaml`` is auto-discovered
    relative to the script (matching the behavior of ``python main.py`` from
    the project root).
    """
    script = script.resolve()
    if not script.is_file():
        raise FileNotFoundError(f"Script not found: {script}")

    previous_argv = sys.argv[:]
    previous_cwd = os.getcwd()
    sys.argv = [str(script)]
    try:
        os.chdir(script.parent)
        runpy.run_path(str(script), run_name="__main__")
    finally:
        sys.argv = previous_argv
        os.chdir(previous_cwd)

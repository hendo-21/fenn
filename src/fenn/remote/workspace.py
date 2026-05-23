"""Pack the local project workspace into a gzipped tarball for upload.

We tar the user's CWD with sensible excludes so they don't have to think about
data files / helper modules — the server gets everything it needs to run
``python main.py`` in an isolated working directory.

Exclusion rules (in order):

1. Hard-coded defaults: ``logger/``, ``export/``, ``__pycache__/``, ``.git/``,
   ``.venv/``, ``.mypy_cache/``, ``.pytest_cache/``, ``.idea/``, ``.vscode/``.
2. Patterns from ``.fennignore`` (one shell-style glob per line, ``#`` comments).
3. User-supplied ``extra_excludes`` (shell-style globs).

A hard size cap on the *uncompressed* total prevents accidental uploads of
multi-gigabyte datasets.
"""

from __future__ import annotations

import fnmatch
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from fenn.remote.exceptions import WorkspaceTooLargeError

DEFAULT_EXCLUDES: tuple[str, ...] = (
    "logger",
    "export",
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    ".idea",
    ".vscode",
    ".DS_Store",
    "*.pyc",
)

DEFAULT_MAX_BYTES = 100 * 1024 * 1024  # 100 MB uncompressed


@dataclass
class WorkspacePack:
    """Handle to a packed workspace tarball.

    ``path`` is a ``NamedTemporaryFile``-backed gzip; the caller is responsible
    for deleting it (use :meth:`cleanup` in a ``finally`` block).
    """

    path: Path
    uncompressed_bytes: int
    file_count: int
    script_relpath: str

    def cleanup(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def _load_fennignore(root: Path) -> List[str]:
    path = root / ".fennignore"
    if not path.exists():
        return []
    patterns: List[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line)
    return patterns


def _is_excluded(rel: Path, patterns: Sequence[str]) -> bool:
    parts = rel.parts
    name = rel.name
    posix = rel.as_posix()
    for pattern in patterns:
        # Directory or file name component match (e.g. "logger" matches any
        # path containing a "logger" component) — same UX as .gitignore for
        # simple bare names.
        if "/" not in pattern and "*" not in pattern and "?" not in pattern:
            if pattern in parts:
                return True
            continue
        # Glob: match against the full POSIX path and the basename.
        if fnmatch.fnmatch(posix, pattern) or fnmatch.fnmatch(name, pattern):
            return True
    return False


def pack_workspace(
    root: Path,
    script: Path,
    *,
    extra_includes: Optional[Iterable[Path]] = None,
    extra_excludes: Optional[Iterable[str]] = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> WorkspacePack:
    """Tar+gzip ``root`` into a tempfile.

    Args:
        root: Project directory to pack. Must be an existing directory.
        script: Path (absolute or relative to ``root``) of the entrypoint
            script. Must live underneath ``root``. Returned in
            :attr:`WorkspacePack.script_relpath` as a POSIX relative path so
            the server can locate it in the unpacked workdir.
        extra_includes: Paths that should be force-included even if they would
            otherwise be excluded.
        extra_excludes: Additional shell-glob patterns to skip.
        max_bytes: Cap on the uncompressed total. Raises
            :class:`WorkspaceTooLargeError` if exceeded.

    Returns:
        A :class:`WorkspacePack` pointing at the gzipped tarball.
    """
    root = root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Workspace root not found: {root}")

    if not script.is_absolute():
        script = (root / script).resolve()
    else:
        script = script.resolve()

    try:
        script_rel = script.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            f"Script {script} must live inside the workspace root {root}"
        ) from exc

    if not script.is_file():
        raise FileNotFoundError(f"Entrypoint script not found: {script}")

    patterns = list(DEFAULT_EXCLUDES)
    patterns.extend(_load_fennignore(root))
    if extra_excludes:
        patterns.extend(extra_excludes)

    force_include = {
        p.resolve().relative_to(root)
        for p in (extra_includes or [])
        if p.resolve().is_relative_to(root)
    }

    tmp = tempfile.NamedTemporaryFile(
        prefix="fenn-workspace-", suffix=".tar.gz", delete=False
    )
    tmp.close()
    tar_path = Path(tmp.name)

    total_bytes = 0
    file_count = 0
    try:
        with tarfile.open(tar_path, mode="w:gz") as tar:
            for file_path in sorted(root.rglob("*")):
                if not file_path.is_file():
                    continue
                rel = file_path.relative_to(root)
                if rel not in force_include and _is_excluded(rel, patterns):
                    continue

                size = file_path.stat().st_size
                total_bytes += size
                if total_bytes > max_bytes:
                    raise WorkspaceTooLargeError(
                        f"Workspace exceeds {max_bytes:,} bytes "
                        f"(uncompressed). Add entries to .fennignore or pass "
                        f"--exclude. Hit the limit at {rel.as_posix()!r}."
                    )
                file_count += 1
                # Store paths POSIX-style (forward slashes) so the server can
                # decompress safely on any OS.
                tar.add(file_path, arcname=rel.as_posix(), recursive=False)
    except BaseException:
        tar_path.unlink(missing_ok=True)
        raise

    return WorkspacePack(
        path=tar_path,
        uncompressed_bytes=total_bytes,
        file_count=file_count,
        script_relpath=script_rel.as_posix(),
    )

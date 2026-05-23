"""Safe extraction of a remote artifact tarball into the local workspace.

The server sends a ``.tar.gz`` containing ``logger/`` and ``export/`` trees so
the local on-disk state mirrors what a local run would have produced. We
extract with explicit path-traversal protection (no ``..``, no absolute paths,
no symlinks, no device files) so a malicious server can't write outside the
destination directory.
"""

from __future__ import annotations

import tarfile
from pathlib import Path
from typing import List


def extract_artifacts(tarball: Path, dest: Path) -> List[str]:
    """Extract ``tarball`` into ``dest``. Returns the list of written paths.

    Existing files in ``dest`` are overwritten (the remote run is the source
    of truth for log/export directories).
    """
    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    written: List[str] = []
    with tarfile.open(tarball, mode="r:*") as tar:
        for member in tar.getmembers():
            if not (member.isfile() or member.isdir()):
                # skip symlinks, device files, etc.
                continue
            name = member.name
            if name.startswith("/") or ".." in Path(name).parts:
                raise ValueError(f"Refusing to extract unsafe path: {name!r}")
            target = (dest / name).resolve()
            try:
                target.relative_to(dest)
            except ValueError as exc:
                raise ValueError(
                    f"Refusing to extract path escaping destination: {name!r}"
                ) from exc

            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            extracted = tar.extractfile(member)
            if extracted is None:
                continue
            with open(target, "wb") as fh:
                while True:
                    chunk = extracted.read(64 * 1024)
                    if not chunk:
                        break
                    fh.write(chunk)
            written.append(name)
    return written

"""Tests for fenn.remote.workspace."""

from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

from fenn.remote.exceptions import WorkspaceTooLargeError
from fenn.remote.workspace import pack_workspace


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "main.py").write_text("print('hi')\n")
    (tmp_path / "fenn.yaml").write_text("project: test\n")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "x.csv").write_text("a,b\n1,2\n")
    # excluded by default
    (tmp_path / "logger").mkdir()
    (tmp_path / "logger" / "x.fn").write_text("<fenn-log/>")
    (tmp_path / "export").mkdir()
    (tmp_path / "export" / "model.bin").write_text("BIN")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "main.cpython-312.pyc").write_text("X")
    return tmp_path


def _members(tar_path: Path) -> set[str]:
    with tarfile.open(tar_path, mode="r:*") as tar:
        return {m.name for m in tar.getmembers() if m.isfile()}


def test_pack_includes_user_files_and_skips_defaults(project):
    pack = pack_workspace(project, project / "main.py")
    try:
        names = _members(pack.path)
        assert "main.py" in names
        assert "fenn.yaml" in names
        assert "data/x.csv" in names
        assert not any(n.startswith("logger/") for n in names)
        assert not any(n.startswith("export/") for n in names)
        assert not any(n.startswith(".git/") for n in names)
        assert not any(n.startswith("__pycache__/") for n in names)
        assert pack.script_relpath == "main.py"
    finally:
        pack.cleanup()


def test_fennignore_is_honored(project):
    (project / ".fennignore").write_text("data\n")
    pack = pack_workspace(project, project / "main.py")
    try:
        names = _members(pack.path)
        assert "main.py" in names
        assert not any(n.startswith("data/") for n in names)
    finally:
        pack.cleanup()


def test_max_bytes_raises(project):
    big = project / "huge.bin"
    big.write_bytes(b"x" * (1024 * 1024))  # 1 MB
    with pytest.raises(WorkspaceTooLargeError):
        pack_workspace(project, project / "main.py", max_bytes=512 * 1024)


def test_script_outside_root_rejected(project, tmp_path):
    other = tmp_path.parent / "outside.py"
    other.write_text("x")
    with pytest.raises(ValueError):
        pack_workspace(project, other)
    other.unlink(missing_ok=True)


def test_extra_excludes(project):
    pack = pack_workspace(
        project, project / "main.py", extra_excludes=["*.csv"]
    )
    try:
        names = _members(pack.path)
        assert "main.py" in names
        assert "data/x.csv" not in names
    finally:
        pack.cleanup()

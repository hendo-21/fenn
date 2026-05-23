"""Tests for fenn.remote.credentials."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from fenn.remote import credentials as creds_module
from fenn.remote.exceptions import CredentialsError


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Point HOME at a tmp dir and reload the module so paths recompute."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows
    monkeypatch.delenv("FENN_API_KEY", raising=False)
    monkeypatch.delenv("FENN_PROFILE", raising=False)
    importlib.reload(creds_module)
    yield tmp_path
    importlib.reload(creds_module)


def test_write_and_load_roundtrip(isolated_home):
    creds_module.write_credentials(
        "fk_live_secret", profile="default", host="https://api.example.com"
    )
    loaded = creds_module.load_credentials("default")
    assert loaded is not None
    assert loaded.api_key == "fk_live_secret"
    assert loaded.host == "https://api.example.com"


def test_multiple_profiles_coexist(isolated_home):
    creds_module.write_credentials("k1", profile="default")
    creds_module.write_credentials("k2", profile="work", host="https://b")
    assert creds_module.load_credentials("default").api_key == "k1"
    work = creds_module.load_credentials("work")
    assert work.api_key == "k2"
    assert work.host == "https://b"


def test_resolve_priority_flag_over_env(isolated_home, monkeypatch):
    monkeypatch.setenv("FENN_API_KEY", "from_env")
    got = creds_module.resolve_api_key(explicit="from_flag")
    assert got.api_key == "from_flag"


def test_resolve_env_over_file(isolated_home, monkeypatch):
    creds_module.write_credentials("from_file", profile="default")
    monkeypatch.setenv("FENN_API_KEY", "from_env")
    got = creds_module.resolve_api_key()
    assert got.api_key == "from_env"


def test_resolve_file_when_no_env(isolated_home, monkeypatch):
    monkeypatch.delenv("FENN_API_KEY", raising=False)
    creds_module.write_credentials("from_file", profile="default")
    got = creds_module.resolve_api_key()
    assert got.api_key == "from_file"


def test_resolve_raises_when_nothing(isolated_home, monkeypatch):
    monkeypatch.delenv("FENN_API_KEY", raising=False)
    with pytest.raises(CredentialsError):
        creds_module.resolve_api_key()


def test_delete_profile(isolated_home):
    creds_module.write_credentials("k1", profile="default")
    creds_module.write_credentials("k2", profile="work")
    assert creds_module.delete_profile("work") is True
    assert creds_module.load_credentials("work") is None
    assert creds_module.load_credentials("default").api_key == "k1"


def test_mask_key():
    assert creds_module.mask_key("short") == "*****"
    masked = creds_module.mask_key("fk_live_abcdefghijklmnop")
    assert masked.startswith("fk_live_")
    assert masked.endswith("mnop")
    assert "..." in masked

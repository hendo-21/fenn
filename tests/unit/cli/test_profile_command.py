"""Unit tests for fenn profile CLI support."""

import logging
from unittest.mock import Mock

import pytest

from fenn.cli import build_parser, profile


def test_profile_parser_defaults() -> None:
    parser = build_parser()
    args = parser.parse_args(["profile", "default"])

    assert args.command == "profile"
    assert args.template == "default"
    assert args.limit == 25


def test_profile_parser_accepts_limit() -> None:
    parser = build_parser()
    args = parser.parse_args(["profile", "default", "--limit", "10"])

    assert args.limit == 10


@pytest.mark.parametrize("template_name", ["default", "nested/default"])
def test_profile_execute_generates_profile_and_report(
    tmp_path, monkeypatch, caplog, template_name
) -> None:
    """Execute profile and verify output files are created and reported."""
    monkeypatch.chdir(tmp_path)

    template_dir = tmp_path / template_name
    template_dir.mkdir(parents=True)
    (template_dir / "main.py").write_text(
        "print('hello')\n",
        encoding="utf-8",
    )

    args = Mock()
    args.template = template_name
    args.limit = 5

    caplog.set_level(logging.INFO)
    profile.execute(args)

    output_dir = tmp_path / "profiling_results" / template_name
    profile_file = output_dir / "cprofile.prof"
    report_file = output_dir / "cprofile.txt"

    assert profile_file.exists(), "Expected profile output file to be created"
    assert report_file.exists(), "Expected profile report to be created"

    log_output = "\n".join(record.getMessage() for record in caplog.records)
    assert "Profile:" in log_output
    assert "Report:" in log_output
    assert str(profile_file) in log_output
    assert str(report_file) in log_output


def test_profile_execute_raises_exit_code(tmp_path, monkeypatch):
    """Verify system exit is raised when profile execute is called on
    template dir missing main.py."""
    monkeypatch.chdir(tmp_path)
    template_dir = tmp_path / "missing_main"
    template_dir.mkdir()

    args = Mock()
    args.template = "missing_main"

    with pytest.raises(SystemExit) as exc_info:
        profile.execute(args)

    assert exc_info.value.code == 1

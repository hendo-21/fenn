"""Tests for fenn.remote.client (SSE parsing + error mapping)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import requests  # noqa: F401  (kept for session construction)

from fenn.remote.client import RemoteClient, _parse_sse
from fenn.remote.exceptions import InsufficientCreditsError, RemoteError


class _FakeResponse:
    def __init__(self, lines):
        self._lines = lines

    def iter_lines(self, decode_unicode=False):
        return iter(self._lines)


def test_parse_sse_extracts_event_and_json_data():
    resp = _FakeResponse(
        [
            "event: log",
            'data: {"line": "hello"}',
            "",
            "event: status",
            'data: {"status": "succeeded"}',
            "",
        ]
    )
    events = list(_parse_sse(resp))
    assert events == [
        {"event": "log", "data": {"line": "hello"}},
        {"event": "status", "data": {"status": "succeeded"}},
    ]


def test_parse_sse_falls_back_to_raw_string():
    resp = _FakeResponse(["event: log", "data: plain text", ""])
    events = list(_parse_sse(resp))
    assert events == [{"event": "log", "data": "plain text"}]


def test_parse_sse_skips_keepalive_comments():
    resp = _FakeResponse([":", "event: status", 'data: {"status": "running"}', ""])
    events = list(_parse_sse(resp))
    assert events == [{"event": "status", "data": {"status": "running"}}]


def test_raise_for_status_402_maps_to_typed_error():
    client = RemoteClient("http://x", "k", session=requests.Session())
    resp = MagicMock()
    resp.status_code = 402
    resp.json.return_value = {"detail": "need 50 credits"}
    with pytest.raises(InsufficientCreditsError):
        client._raise_for_status(resp)


def test_raise_for_status_500_falls_through():
    client = RemoteClient("http://x", "k", session=requests.Session())
    resp = MagicMock()
    resp.status_code = 503
    resp.json.side_effect = ValueError()
    resp.text = "down"
    resp.reason = "Service Unavailable"
    with pytest.raises(RemoteError) as exc:
        client._raise_for_status(resp)
    assert "503" in str(exc.value)


def test_url_joining_strips_trailing_slash():
    client = RemoteClient("http://host/", "k", session=requests.Session())
    assert client._url("/v1/me") == "http://host/v1/me"

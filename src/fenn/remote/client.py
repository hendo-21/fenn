"""Thin ``requests``-based client for the Fenn remote execution API.

Kept deliberately minimal — no fancy async, no extra deps. The CLI consumes
this module directly. The transport surface is:

* ``submit_job(tarball, script, max_runtime, project)``  → ``{job_id, ...}``
* ``get_job(job_id)``                                    → JSON record
* ``stream_events(job_id)``                              → iterator of SSE dicts
* ``download_artifacts(job_id, dest)``                   → writes ``dest``
* ``cancel(job_id)``                                     → JSON record
* ``me()``                                               → JSON record
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

import requests

from fenn.remote.exceptions import (
    InsufficientCreditsError,
    RemoteError,
)

DEFAULT_TIMEOUT = (10.0, 60.0)  # (connect, read) seconds for non-streaming calls


class RemoteClient:
    """Synchronous HTTP client for the Fenn remote execution service."""

    def __init__(self, host: str, api_key: str, *, session: Optional[requests.Session] = None) -> None:
        self.host = host.rstrip("/")
        self.api_key = api_key
        self._session = session or requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "fenn-cli",
            }
        )

    # ---- low-level -------------------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self.host}{path}"

    @staticmethod
    def _raise_for_status(resp: requests.Response) -> None:
        if resp.status_code < 400:
            return
        message: str
        try:
            payload = resp.json()
            message = payload.get("detail") or payload.get("message") or resp.text
        except ValueError:
            message = resp.text or resp.reason or "unknown error"

        if resp.status_code == 401:
            raise RemoteError(f"Authentication failed (401): {message}")
        if resp.status_code == 402:
            raise InsufficientCreditsError(message)
        if resp.status_code == 403:
            raise RemoteError(f"Forbidden (403): {message}")
        if resp.status_code == 404:
            raise RemoteError(f"Not found (404): {message}")
        if resp.status_code == 413:
            raise RemoteError(f"Payload too large (413): {message}")
        raise RemoteError(f"HTTP {resp.status_code}: {message}")

    # ---- endpoints -------------------------------------------------------

    def me(self) -> Dict[str, Any]:
        resp = self._session.get(self._url("/v1/me"), timeout=DEFAULT_TIMEOUT)
        self._raise_for_status(resp)
        return resp.json()

    def submit_job(
        self,
        tarball_path: Path,
        *,
        script: str,
        max_runtime: int,
        project: Optional[str] = None,
    ) -> Dict[str, Any]:
        meta = {"max_runtime": max_runtime, "script": script}
        if project:
            meta["project"] = project

        with open(tarball_path, "rb") as fh:
            files = {
                "tarball": (tarball_path.name, fh, "application/gzip"),
            }
            data = {"meta": json.dumps(meta)}
            resp = self._session.post(
                self._url("/v1/jobs"),
                files=files,
                data=data,
                timeout=(DEFAULT_TIMEOUT[0], 300.0),  # allow long upload
            )
        self._raise_for_status(resp)
        return resp.json()

    def get_job(self, job_id: str) -> Dict[str, Any]:
        resp = self._session.get(
            self._url(f"/v1/jobs/{job_id}"), timeout=DEFAULT_TIMEOUT
        )
        self._raise_for_status(resp)
        return resp.json()

    def cancel(self, job_id: str) -> Dict[str, Any]:
        resp = self._session.delete(
            self._url(f"/v1/jobs/{job_id}"), timeout=DEFAULT_TIMEOUT
        )
        self._raise_for_status(resp)
        return resp.json()

    @contextmanager
    def stream_events(self, job_id: str) -> Iterator[Iterator[Dict[str, Any]]]:
        """Open an SSE stream for ``job_id`` and yield decoded events.

        Each yielded item is ``{"event": str, "data": Any}`` where ``data`` is
        ``json.loads``'d if possible, otherwise the raw string.
        """
        resp = self._session.get(
            self._url(f"/v1/jobs/{job_id}/events"),
            headers={"Accept": "text/event-stream"},
            stream=True,
            timeout=(DEFAULT_TIMEOUT[0], None),
        )
        try:
            self._raise_for_status(resp)
            yield _parse_sse(resp)
        finally:
            resp.close()

    def download_artifacts(self, job_id: str, dest: Path) -> Path:
        """Stream the artifact tarball to ``dest`` and return the path."""
        resp = self._session.get(
            self._url(f"/v1/jobs/{job_id}/artifacts"),
            stream=True,
            timeout=(DEFAULT_TIMEOUT[0], None),
        )
        try:
            self._raise_for_status(resp)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        fh.write(chunk)
        finally:
            resp.close()
        return dest

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "RemoteClient":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


def _parse_sse(resp: requests.Response) -> Iterator[Dict[str, Any]]:
    """Iterate Server-Sent Events from a streaming response.

    Yields one dict per event with keys ``event`` (defaults to ``"message"``)
    and ``data`` (decoded from JSON if possible, else the raw string).
    """
    event_name = "message"
    data_buf: list[str] = []
    for raw in resp.iter_lines(decode_unicode=True):
        if raw is None:
            continue
        if raw == "":
            if data_buf:
                payload = "\n".join(data_buf)
                try:
                    decoded: Any = json.loads(payload)
                except ValueError:
                    decoded = payload
                yield {"event": event_name, "data": decoded}
            event_name = "message"
            data_buf = []
            continue
        if raw.startswith(":"):
            # comment / keep-alive
            continue
        if raw.startswith("event:"):
            event_name = raw[6:].strip()
        elif raw.startswith("data:"):
            data_buf.append(raw[5:].lstrip())
    # tail flush (server closing without a trailing blank line)
    if data_buf:
        payload = "\n".join(data_buf)
        try:
            decoded = json.loads(payload)
        except ValueError:
            decoded = payload
        yield {"event": event_name, "data": decoded}

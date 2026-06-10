"""``fenn run`` — execute a Fenn project on the Fenn remote service."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path
from typing import Iterable, Optional

from colorama import Fore, Style

from fenn.remote.exceptions import (
    CredentialsError,
    InsufficientCreditsError,
    JobFailedError,
    RemoteError,
    WorkspaceTooLargeError,
)
from fenn.utils.logging import logger

DEFAULT_SCRIPT = "main.py"
TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}


def execute(args: argparse.Namespace) -> None:
    """Entrypoint wired from :func:`fenn.cli.build_parser`.

    Args:
        args: Parsed arguments with attributes ``script``, ``api_key``,
            ``profile``, ``max_runtime``, ``detach``, ``no_download``,
            ``include``, ``exclude``.
    """
    script_path = _resolve_script(args.script)

    try:
        _run_remote(
            script_path=script_path,
            explicit_key=args.api_key,
            profile=args.profile,
            max_runtime=args.max_runtime * 60,
            detach=args.detach,
            download=not args.no_download,
            includes=args.include or (),
            excludes=args.exclude or (),
        )
    except CredentialsError as exc:
        print(f"{Fore.RED}{exc}{Style.RESET_ALL}", file=sys.stderr)
        sys.exit(2)
    except WorkspaceTooLargeError as exc:
        print(f"{Fore.RED}{exc}{Style.RESET_ALL}", file=sys.stderr)
        sys.exit(2)
    except InsufficientCreditsError as exc:
        print(
            f"{Fore.RED}Insufficient credits: {exc}{Style.RESET_ALL}",
            file=sys.stderr,
        )
        sys.exit(3)
    except JobFailedError as exc:
        print(
            f"{Fore.RED}Remote job {exc.job_id} ended with status "
            f"{exc.status!r}: {exc}{Style.RESET_ALL}",
            file=sys.stderr,
        )
        sys.exit(1)
    except RemoteError as exc:
        print(f"{Fore.RED}Remote error: {exc}{Style.RESET_ALL}", file=sys.stderr)
        sys.exit(1)


def _resolve_script(raw: Optional[str]) -> Path:
    name = raw or DEFAULT_SCRIPT
    candidate = Path(name).resolve()
    if not candidate.is_file():
        print(
            f"{Fore.RED}Script not found: {candidate}{Style.RESET_ALL}",
            file=sys.stderr,
        )
        sys.exit(1)
    return candidate


# ---------------------------------------------------------------------------
# local execution
# ---------------------------------------------------------------------------


def _run_local(script_path: Path) -> None:
    from fenn.remote.local_runner import run_local

    run_local(script_path)


# ---------------------------------------------------------------------------
# remote execution
# ---------------------------------------------------------------------------


def _run_remote(
    *,
    script_path: Path,
    explicit_key: Optional[str],
    profile: Optional[str],
    max_runtime: int,
    detach: bool,
    download: bool,
    includes: Iterable[str],
    excludes: Iterable[str],
) -> None:
    from fenn.remote.artifacts import extract_artifacts
    from fenn.remote.client import DEFAULT_REMOTE_HOST, RemoteClient
    from fenn.remote.credentials import resolve_api_key
    from fenn.remote.workspace import detect_venv_spec, pack_workspace

    creds = resolve_api_key(explicit=explicit_key, profile=profile)

    root = Path.cwd().resolve()
    include_paths = [Path(p) for p in includes]
    project = _read_project_name(root)

    print(
        f"{Fore.CYAN}Packing workspace from {Fore.LIGHTYELLOW_EX}{root}{Style.RESET_ALL}",
        file=sys.stderr,
    )
    pack = pack_workspace(
        root=root,
        script=script_path,
        extra_includes=include_paths,
        extra_excludes=excludes,
    )

    venv_spec = detect_venv_spec(root)
    if venv_spec:
        print(
            f"{Fore.CYAN}Found {Fore.LIGHTYELLOW_EX}{venv_spec['requirements']}"
            f"{Fore.CYAN} — remote will build a temporary venv and install "
            f"dependencies before running.{Style.RESET_ALL}",
            file=sys.stderr,
        )

    try:
        with RemoteClient(DEFAULT_REMOTE_HOST, creds.api_key) as client:
            print(
                f"{Fore.CYAN}Submitting {pack.file_count} files "
                f"({pack.uncompressed_bytes / 1024:,.1f} KB) to "
                f"{Fore.LIGHTYELLOW_EX}{DEFAULT_REMOTE_HOST}{Style.RESET_ALL}",
                file=sys.stderr,
            )
            submission = client.submit_job(
                pack.path,
                script=pack.script_relpath,
                max_runtime=max_runtime,
                project=project,
                venv=venv_spec,
            )
            job_id = submission["job_id"]
            hold = submission.get("credit_hold")
            print(
                f"{Fore.GREEN}Job {Fore.LIGHTYELLOW_EX}{job_id}{Fore.GREEN} "
                f"submitted (hold: {hold} credits).{Style.RESET_ALL}",
                file=sys.stderr,
            )

            if detach:
                print(
                    f"{Fore.CYAN}--detach set; not streaming. "
                    f"Save this job id to check later.{Style.RESET_ALL}",
                    file=sys.stderr,
                )
                return

            final_status, billing = _stream_to_completion(client, job_id)

            if download:
                tmp = tempfile.NamedTemporaryFile(
                    prefix=f"fenn-artifacts-{job_id}-", suffix=".tar.gz", delete=False
                )
                tmp.close()
                tar_path = Path(tmp.name)
                try:
                    client.download_artifacts(job_id, tar_path)
                    written = extract_artifacts(tar_path, root)
                    print(
                        f"{Fore.GREEN}Downloaded {len(written)} files into "
                        f"{Fore.LIGHTYELLOW_EX}{root}{Style.RESET_ALL}",
                        file=sys.stderr,
                    )
                finally:
                    tar_path.unlink(missing_ok=True)

            _print_summary(final_status, billing)

            if final_status not in {"succeeded"}:
                raise JobFailedError(
                    f"job ended in status {final_status!r}",
                    job_id=job_id,
                    status=final_status,
                )
    finally:
        pack.cleanup()


def _stream_to_completion(client, job_id: str) -> tuple[str, dict]:
    """Open SSE, render log/status/billing events, return (final_status, last_billing)."""
    final_status = "unknown"
    last_billing: dict = {}
    try:
        with client.stream_events(job_id) as events:
            for evt in events:
                kind = evt.get("event", "message")
                data = evt.get("data")
                if kind == "log":
                    _render_log(data)
                elif kind == "status":
                    status = _coerce_status(data)
                    print(
                        f"{Fore.CYAN}[status] {status}{Style.RESET_ALL}",
                        file=sys.stderr,
                    )
                    if status in TERMINAL_STATUSES:
                        final_status = status
                        break
                elif kind == "billing":
                    if isinstance(data, dict):
                        last_billing = data
                else:
                    # unknown event kind — show raw
                    print(
                        f"{Fore.LIGHTBLACK_EX}[{kind}] {data}{Style.RESET_ALL}",
                        file=sys.stderr,
                    )
    except KeyboardInterrupt:
        print(
            f"{Fore.YELLOW}Interrupted — cancelling remote job...{Style.RESET_ALL}",
            file=sys.stderr,
        )
        try:
            client.cancel(job_id)
        except RemoteError as exc:
            print(
                f"{Fore.RED}Cancel request failed: {exc}{Style.RESET_ALL}",
                file=sys.stderr,
            )
        raise
    return final_status, last_billing


def _render_log(data) -> None:
    if isinstance(data, dict):
        line = data.get("line") or data.get("text") or str(data)
    else:
        line = str(data)
    # Logs from the remote already carry their own colorization (the user's
    # script ran with the same fenn logger). Pass through as-is.
    logger.info(line)


def _coerce_status(data) -> str:
    if isinstance(data, dict):
        return str(data.get("status", "unknown"))
    return str(data)


def _print_summary(final_status: str, billing: dict) -> None:
    used = billing.get("credits_used")
    remaining = billing.get("credits_remaining")
    wall = billing.get("wall_seconds")
    color = Fore.GREEN if final_status == "succeeded" else Fore.RED
    parts = [f"status={final_status}"]
    if wall is not None:
        parts.append(f"wall={wall:.1f}s")
    if used is not None:
        parts.append(f"credits_used={used}")
    if remaining is not None:
        parts.append(f"credits_remaining={remaining}")
    print(f"{color}[summary] {' '.join(parts)}{Style.RESET_ALL}", file=sys.stderr)


def _read_project_name(root: Path) -> Optional[str]:
    yaml_path = root / "fenn.yaml"
    if not yaml_path.exists():
        return None
    try:
        import yaml

        with open(yaml_path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        project = data.get("project")
        return str(project) if project else None
    except Exception:
        return None

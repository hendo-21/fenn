"""FnXML file discovery and parsing for the Fenn dashboard."""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET

# Default directories to scan (resolved at runtime)
_DEFAULT_DIRS = [
    "./logger",
    "~/logger",
    "~/.fenn/logs",
]


class FennScanner:
    """Discovers and parses .fn log files from configured directories."""

    def __init__(self, extra_dirs: Optional[List[str]] = None) -> None:
        self._dirs: List[Path] = []

        # Load from environment variable
        env_dirs = os.environ.get("FENN_LOG_DIRS", "")
        if env_dirs:
            for d in env_dirs.split(":"):
                self._add_dir(d)

        # Add defaults
        for d in _DEFAULT_DIRS:
            self._add_dir(d)

        # Add any extra dirs passed explicitly
        if extra_dirs:
            for d in extra_dirs:
                self._add_dir(d)

    def add_dirs(self, dirs: List[str]) -> None:
        for d in dirs:
            self._add_dir(d)

    def _add_dir(self, path: str) -> None:
        p = Path(path).expanduser().resolve()
        if p not in self._dirs:
            self._dirs.append(p)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def find_fn_files(self) -> List[Path]:
        """Return all .fn files sorted by modification time (newest first)."""
        files: List[Path] = []
        for d in self._dirs:
            if d.exists() and d.is_dir():
                files.extend(d.rglob("*.fn"))
        seen = set()
        unique = []
        for f in files:
            if f not in seen:
                seen.add(f)
                unique.append(f)
        return sorted(unique, key=lambda f: f.stat().st_mtime, reverse=True)

    def parse_fn_file(self, path: Path) -> Optional[Dict[str, Any]]:
        """Parse a single .fn file. Handles incomplete (running) sessions."""
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, PermissionError):
            return None

        root = None
        status = "completed"

        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            # Session may still be running — try appending the closing tag
            try:
                root = ET.fromstring(content + "\n</fenn-log>")
                status = "running"
            except ET.ParseError:
                return None

        # Override status from <meta> if present
        meta = root.find("meta")
        if meta is not None:
            status = meta.get("status", "completed")

        # Config
        config: Dict[str, str] = {}
        config_el = root.find("config")
        if config_el is not None:
            for item in config_el.findall("item"):
                k = item.get("key", "")
                v = item.get("value", "")
                if k:
                    config[k] = v

        # Log entries
        entries = []
        for entry in root.findall("entry"):
            entries.append(
                {
                    "ts": entry.get("ts", ""),
                    "kind": entry.get("kind", ""),
                    "level": entry.get("level", ""),
                    "message": entry.text or "",
                }
            )

        # Timing from <meta>
        ended: Optional[str] = None
        duration_s: Optional[int] = None
        if meta is not None:
            ended = meta.get("ended")
            try:
                duration_s = int(meta.get("duration_s", 0))
            except (ValueError, TypeError):
                pass

        warnings = sum(1 for e in entries if e["level"] == "warning")
        exceptions = sum(1 for e in entries if e["level"] == "exception")

        try:
            file_size = path.stat().st_size
            file_mtime = path.stat().st_mtime
        except OSError:
            file_size = 0
            file_mtime = 0.0

        return {
            "session_id": root.get("session_id", path.stem),
            "project": root.get("project", path.parent.name),
            "started": root.get("started", ""),
            "ended": ended,
            "duration_s": duration_s,
            "status": status,
            "config": config,
            "entries": entries,
            "entry_count": len(entries),
            "warning_count": warnings,
            "exception_count": exceptions,
            "file_path": str(path),
            "file_size": file_size,
            "file_mtime": file_mtime,
        }

    def get_all_sessions(self) -> List[Dict[str, Any]]:
        """Return all parsed sessions, newest first."""
        sessions = []
        for path in self.find_fn_files():
            parsed = self.parse_fn_file(path)
            if parsed:
                sessions.append(parsed)
        return sessions

    def get_overview(self) -> Dict[str, Any]:
        """Aggregate stats for the dashboard home page."""
        sessions = self.get_all_sessions()

        # Group by project
        projects: Dict[str, Dict[str, Any]] = {}
        for s in sessions:
            name = s["project"]
            if name not in projects:
                projects[name] = {
                    "name": name,
                    "session_count": 0,
                    "running_count": 0,
                    "warning_count": 0,
                    "exception_count": 0,
                    "last_active": s["started"],
                }
            p = projects[name]
            p["session_count"] += 1
            p["warning_count"] += s["warning_count"]
            p["exception_count"] += s["exception_count"]
            if s["status"] == "running":
                p["running_count"] += 1

        project_list = sorted(
            projects.values(), key=lambda p: p["last_active"], reverse=True
        )

        total_warnings = sum(s["warning_count"] for s in sessions)
        total_exceptions = sum(s["exception_count"] for s in sessions)
        running = sum(1 for s in sessions if s["status"] == "running")

        return {
            "projects": project_list,
            "recent_sessions": sessions[:20],
            "total_sessions": len(sessions),
            "total_projects": len(projects),
            "total_warnings": total_warnings,
            "total_exceptions": total_exceptions,
            "running_sessions": running,
            "active_page": "home",
        }

    def get_project(self, project_name: str) -> Dict[str, Any]:
        """Return all sessions for a specific project."""
        all_sessions = self.get_all_sessions()
        sessions = [s for s in all_sessions if s["project"] == project_name]

        overview = self.get_overview()

        return {
            "projects": overview["projects"],
            "project_name": project_name,
            "sessions": sessions,
            "total_sessions": len(sessions),
            "running_sessions": sum(1 for s in sessions if s["status"] == "running"),
            "total_warnings": sum(s["warning_count"] for s in sessions),
            "total_exceptions": sum(s["exception_count"] for s in sessions),
            "active_page": "project",
            "active_project": project_name,
        }

    def get_session(
        self, project_name: str, session_id: str
    ) -> Optional[Dict[str, Any]]:
        """Return full data for a single session."""
        for path in self.find_fn_files():
            parsed = self.parse_fn_file(path)
            if (
                parsed
                and parsed["project"] == project_name
                and parsed["session_id"] == session_id
            ):
                overview = self.get_overview()
                return {
                    **parsed,
                    "projects": overview["projects"],
                    "active_page": "session",
                    "active_project": project_name,
                }
        return None

    def format_duration(self, seconds: Optional[int]) -> str:
        if seconds is None:
            return "—"
        if seconds < 60:
            return f"{seconds}s"
        if seconds < 3600:
            return f"{seconds // 60}m {seconds % 60}s"
        h = seconds // 3600
        m = (seconds % 3600) // 60
        return f"{h}h {m}m"

    def format_size(self, size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        if size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        return f"{size_bytes / (1024 * 1024):.1f} MB"

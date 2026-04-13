"""Fenn Dashboard — Flask application for browsing fnxml log files."""

import argparse
import logging
from pathlib import Path

from flask import Flask, abort, jsonify, render_template

try:
    from fenn.dashboard.scanner import FennScanner
except ImportError:  # standalone: python app.py
    from scanner import FennScanner  # type: ignore[no-redef]

_HERE = Path(__file__).parent

app = Flask(
    __name__,
    template_folder=str(_HERE / "templates"),
    static_folder=str(_HERE / "static"),
)

scanner = FennScanner()


# --------------------------------------------------------------------------- #
# Template filters
# --------------------------------------------------------------------------- #


@app.template_filter("duration")
def duration_filter(seconds):
    return scanner.format_duration(seconds)


@app.template_filter("filesize")
def filesize_filter(size):
    return scanner.format_size(size)


@app.template_filter("short_id")
def short_id_filter(session_id: str) -> str:
    return session_id[:8] if len(session_id) > 8 else session_id


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


@app.route("/")
def index():
    return render_template("index.html", **scanner.get_overview())


@app.route("/project/<project_name>")
def project(project_name: str):
    return render_template("project.html", **scanner.get_project(project_name))


@app.route("/session/<project_name>/<session_id>")
def session(project_name: str, session_id: str):
    data = scanner.get_session(project_name, session_id)
    if data is None:
        abort(404)
    return render_template("session.html", **data)


@app.route("/api/overview")
def api_overview():
    return jsonify(scanner.get_overview())


@app.route("/api/session/<project_name>/<session_id>")
def api_session(project_name: str, session_id: str):
    data = scanner.get_session(project_name, session_id)
    if data is None:
        abort(404)
    data.pop("projects", None)
    return jsonify(data)


@app.errorhandler(404)
def not_found(e):
    return render_template("404.html", **scanner.get_overview()), 404


# --------------------------------------------------------------------------- #
# Public API (used by CLI)
# --------------------------------------------------------------------------- #


def run(
    host: str = "127.0.0.1", port: int = 5000, debug: bool = False, log_dirs=None
) -> None:
    """Configure and start the dashboard server."""
    if log_dirs:
        scanner.add_dirs(log_dirs)
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app.logger.setLevel(logging.ERROR)
    print(f"Fenn dashboard started at http://{host}:{port}")
    from werkzeug.serving import make_server

    make_server(host, port, app).serve_forever()


# --------------------------------------------------------------------------- #
# Standalone entry point
# --------------------------------------------------------------------------- #


def main():
    parser = argparse.ArgumentParser(
        prog="fenn-dashboard",
        description="Fenn Dashboard — browse fnxml log files in your browser",
    )
    parser.add_argument(
        "--log-dir",
        nargs="+",
        metavar="DIR",
        help="Extra directories to scan for .fn files",
    )
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    run(host=args.host, port=args.port, debug=args.debug, log_dirs=args.log_dir)


if __name__ == "__main__":
    main()

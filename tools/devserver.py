#!/usr/bin/env python3
"""Development stand-in for the Jakarta EE backend.

The production backend is ``backend/`` -- Jakarta EE 10 on Open Liberty with
MicroProfile, JPA and a relational store.  It needs Maven and a container to
run, which is more than a demo or a CI job should require, so this module
implements the *same REST contract* (``docs/06-api.md``) on the Python standard
library, backed by an append-only JSONL file.

The two are not alternatives in production.  This one exists so the relay, the
dashboard and the integration tests can be exercised on any machine with Python
and nothing else.  Anything it does that the Java backend does not, or vice
versa, is a bug in one of them -- ``tools/test_devserver.py`` checks the
contract, and the same cases are the acceptance criteria for the Java resources.

Usage::

    python tools/devserver.py                    # http://localhost:8080
    python tools/devserver.py --port 9000 --store /tmp/alerts.jsonl
"""

from __future__ import annotations

import argparse
import json
import logging
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger("devserver")

REPO_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_DIR = REPO_ROOT / "dashboard"

#: Terminal states, mirroring escalation.model.AlertState.  Duplicated rather
#: than imported so the server stays dependency-free and can be run from a
#: checkout without the package on the path.
TERMINAL_STATES = {
    "ACKNOWLEDGED_BY_OWNER",
    "ACKNOWLEDGED_BY_CAREGIVER",
    "ESCALATED_EMERGENCY",
    "DISMISSED_FALSE_POSITIVE",
    "CANCELLED",
}


class AlertStore:
    """Append-only JSONL store with an in-memory index.

    Append-only on purpose: this is an audit log for a safety system, and "what
    did the system do, and when did it know it" is the question it has to answer
    afterwards.  A row is never rewritten; a state change is a new row and the
    latest row per ``alert_id`` wins.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._alerts: dict[str, dict] = {}
        self._heartbeats: dict[str, dict] = {}
        self._suppressed: list[dict] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        with self.path.open() as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("skipping unparseable row in %s", self.path)
                    continue
                self._apply(record)
        logger.info("loaded %d alerts from %s", len(self._alerts), self.path)

    def _apply(self, record: dict) -> None:
        kind = record.get("kind")
        if kind == "alert":
            self._alerts[record["payload"]["alert_id"]] = record["payload"]
        elif kind == "heartbeat":
            self._heartbeats[record["payload"]["relay_id"]] = record["payload"]
        elif kind == "suppressed":
            self._suppressed.append(record["payload"])

    def _append(self, kind: str, payload: dict) -> None:
        record = {"kind": kind, "received_at": time.time(), "payload": payload}
        with self.path.open("a") as handle:
            handle.write(json.dumps(record) + "\n")
        self._apply(record)

    # ------------------------------------------------------------------ #
    def upsert_alert(self, payload: dict) -> dict:
        with self._lock:
            self._append("alert", payload)
            return payload

    def record_heartbeat(self, payload: dict) -> dict:
        payload = {**payload, "received_at": time.time()}
        with self._lock:
            self._append("heartbeat", payload)
            return payload

    def record_suppressed(self, payload: dict) -> dict:
        with self._lock:
            self._append("suppressed", payload)
            return payload

    def alerts(self, state: str | None = None, dog_id: str | None = None) -> list[dict]:
        with self._lock:
            rows = list(self._alerts.values())
        if state:
            rows = [r for r in rows if r.get("state") == state]
        if dog_id:
            rows = [r for r in rows if r.get("dog_id") == dog_id]
        return sorted(rows, key=lambda r: r.get("raised_at_seconds", 0), reverse=True)

    def alert(self, alert_id: str) -> dict | None:
        with self._lock:
            return self._alerts.get(alert_id)

    def heartbeats(self) -> list[dict]:
        with self._lock:
            return list(self._heartbeats.values())

    def suppressed(self) -> list[dict]:
        with self._lock:
            return list(self._suppressed)

    def summary(self) -> dict:
        rows = self.alerts()
        by_state: dict[str, int] = {}
        for row in rows:
            by_state[row.get("state", "UNKNOWN")] = by_state.get(row.get("state", "UNKNOWN"), 0) + 1

        response_times = [
            row["owner_response_seconds"]
            for row in rows
            if row.get("owner_response_seconds") is not None
        ]
        escalated = by_state.get("ACKNOWLEDGED_BY_CAREGIVER", 0) + by_state.get(
            "ESCALATED_EMERGENCY", 0
        )
        dismissed = by_state.get("DISMISSED_FALSE_POSITIVE", 0)
        total = len(rows)

        return {
            "total_alerts": total,
            "open_alerts": sum(1 for r in rows if r.get("state") not in TERMINAL_STATES),
            "by_state": by_state,
            "escalated": escalated,
            "escalation_rate": escalated / total if total else 0.0,
            "dismissed_false_positive": dismissed,
            "false_positive_rate": dismissed / total if total else 0.0,
            "suppressed_detections": len(self.suppressed()),
            "owner_response": {
                "n": len(response_times),
                "mean_seconds": (
                    sum(response_times) / len(response_times) if response_times else None
                ),
                "max_seconds": max(response_times) if response_times else None,
            },
            "relays": self.heartbeats(),
        }


class Handler(BaseHTTPRequestHandler):
    server_version = "CanineAlertDevServer/1.0"
    store: AlertStore
    api_key: str = ""

    # -- plumbing ------------------------------------------------------- #
    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info("%s - %s", self.address_string(), fmt % args)

    def _json(self, status: HTTPStatus, payload: Any) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        # The dashboard may be opened from a file:// URL during development.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: HTTPStatus, message: str) -> None:
        self._json(status, {"error": message, "status": int(status)})

    def _authorised(self) -> bool:
        if not self.api_key:
            return True
        return self.headers.get("X-API-Key") == self.api_key

    def _read_json(self) -> dict | None:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            self._error(HTTPStatus.BAD_REQUEST, "empty request body")
            return None
        if length > 1_000_000:
            self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "body too large")
            return None
        try:
            return json.loads(self.rfile.read(length))
        except json.JSONDecodeError as error:
            self._error(HTTPStatus.BAD_REQUEST, f"invalid JSON: {error}")
            return None

    # -- routes --------------------------------------------------------- #
    def do_OPTIONS(self) -> None:  # noqa: N802
        self._json(HTTPStatus.NO_CONTENT, {})

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorised():
            self._error(HTTPStatus.UNAUTHORIZED, "bad or missing X-API-Key")
            return

        path = urlparse(self.path).path
        payload = self._read_json()
        if payload is None:
            return

        if path == "/api/v1/alerts":
            if "alert_id" not in payload or "state" not in payload:
                self._error(HTTPStatus.BAD_REQUEST, "alert requires alert_id and state")
                return
            self._json(HTTPStatus.ACCEPTED, self.store.upsert_alert(payload))
        elif path == "/api/v1/heartbeats":
            if "relay_id" not in payload:
                self._error(HTTPStatus.BAD_REQUEST, "heartbeat requires relay_id")
                return
            self._json(HTTPStatus.ACCEPTED, self.store.record_heartbeat(payload))
        elif path == "/api/v1/detections/suppressed":
            self._json(HTTPStatus.ACCEPTED, self.store.record_suppressed(payload))
        else:
            self._error(HTTPStatus.NOT_FOUND, f"no such endpoint: {path}")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path in ("/", "/index.html", "/dashboard"):
            self._serve_dashboard()
            return
        if path == "/health":
            self._json(HTTPStatus.OK, {"status": "UP", "checks": []})
            return

        if not self._authorised():
            self._error(HTTPStatus.UNAUTHORIZED, "bad or missing X-API-Key")
            return

        if path == "/api/v1/alerts":
            self._json(
                HTTPStatus.OK,
                {
                    "alerts": self.store.alerts(
                        state=query.get("state", [None])[0],
                        dog_id=query.get("dog_id", [None])[0],
                    )
                },
            )
        elif path.startswith("/api/v1/alerts/"):
            alert_id = path.rsplit("/", 1)[-1]
            alert = self.store.alert(alert_id)
            if alert is None:
                self._error(HTTPStatus.NOT_FOUND, f"no such alert: {alert_id}")
            else:
                self._json(HTTPStatus.OK, alert)
        elif path == "/api/v1/summary":
            self._json(HTTPStatus.OK, self.store.summary())
        elif path == "/api/v1/heartbeats":
            self._json(HTTPStatus.OK, {"relays": self.store.heartbeats()})
        else:
            self._error(HTTPStatus.NOT_FOUND, f"no such endpoint: {path}")

    def _serve_dashboard(self) -> None:
        page = DASHBOARD_DIR / "index.html"
        if not page.exists():
            self._error(HTTPStatus.NOT_FOUND, "dashboard/index.html is missing")
            return
        body = page.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(port: int, store_path: Path, api_key: str = "") -> ThreadingHTTPServer:
    """Build a server without starting it, so tests can drive it directly."""
    Handler.store = AlertStore(store_path)
    Handler.api_key = api_key
    return ThreadingHTTPServer(("", port), Handler)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--store", type=Path, default=REPO_ROOT / "data" / "alerts.jsonl")
    parser.add_argument("--api-key", default="", help="require this X-API-Key on every call")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")

    httpd = serve(args.port, args.store, args.api_key)
    print(f"dev backend on http://localhost:{args.port}")
    print(f"  dashboard  http://localhost:{args.port}/")
    print(f"  store      {args.store}")
    if args.api_key:
        print("  API key required on /api/v1/*")
    print("\nThis is a development stand-in for backend/ (Jakarta EE). Ctrl-C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

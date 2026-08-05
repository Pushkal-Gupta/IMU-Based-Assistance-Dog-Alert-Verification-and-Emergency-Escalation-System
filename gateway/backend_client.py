"""HTTP client for the caregiver backend.

Uses only the standard library so the relay has no install step beyond Python
itself, and so it runs identically on a laptop and inside a Termux/Pydroid
environment on an Android handset.

The client is deliberately *best-effort*: a backend that is down must never
prevent or delay a page.  Every method swallows transport errors, returns a
success flag, and queues the payload for a later flush.  The escalation ladder
runs entirely on the relay; the backend is the audit log and the caregiver's
dashboard, not the decision-maker.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class BackendClient:
    """Posts alert lifecycle events to the backend's REST API."""

    base_url: str
    api_key: str = ""
    timeout_seconds: float = 3.0
    #: Events that could not be delivered, retried on the next successful call.
    #: Bounded, because an offline relay must not grow until the phone runs out
    #: of memory -- and the oldest events are the least useful ones to keep.
    max_queue: int = 500
    _queue: deque = field(default_factory=deque, init=False, repr=False)
    _reachable: bool = field(default=True, init=False, repr=False)

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        self._queue = deque(maxlen=self.max_queue)

    # ------------------------------------------------------------------ #
    def report_alert(self, alert_payload: dict[str, Any]) -> bool:
        """Upsert an alert and its current state.

        Idempotent on the backend, keyed by ``alert_id``, so replaying the queue
        after an outage cannot create duplicates.
        """
        return self._post("/api/v1/alerts", alert_payload)

    def report_heartbeat(self, dog_id: str, relay_id: str, open_alerts: int) -> bool:
        """Tell the backend the relay is alive.

        This is what lets the backend escalate on the relay's behalf when the
        owner's phone dies mid-alert -- the failure mode a phone-only design
        cannot cover.
        """
        return self._post(
            "/api/v1/heartbeats",
            {"dog_id": dog_id, "relay_id": relay_id, "open_alerts": open_alerts},
        )

    def report_suppressed(self, detection: dict[str, Any], reason: str) -> bool:
        """Log a detection that did not meet the confidence gate.

        Worth recording even though nobody was paged: a rising rate of
        near-miss detections is an early sign the dog's alert is drifting or the
        collar has shifted.
        """
        return self._post("/api/v1/detections/suppressed", {**detection, "reason": reason})

    # ------------------------------------------------------------------ #
    @property
    def reachable(self) -> bool:
        return self._reachable

    @property
    def pending(self) -> int:
        return len(self._queue)

    def flush(self) -> int:
        """Try to deliver queued events.  Returns how many got through."""
        delivered = 0
        while self._queue:
            path, payload = self._queue[0]
            if not self._send(path, payload):
                break
            self._queue.popleft()
            delivered += 1
        return delivered

    # ------------------------------------------------------------------ #
    def _post(self, path: str, payload: dict[str, Any]) -> bool:
        # Drain anything queued first, so the backend sees events in order.
        if self._queue:
            self.flush()
        if self._send(path, payload):
            return True
        if len(self._queue) == self._queue.maxlen:
            logger.warning("backend queue full; dropping the oldest event")
        self._queue.append((path, payload))
        return False

    def _send(self, path: str, payload: dict[str, Any]) -> bool:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                **({"X-API-Key": self.api_key} if self.api_key else {}),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                if 200 <= response.status < 300:
                    if not self._reachable:
                        logger.info("backend reachable again")
                    self._reachable = True
                    return True
                logger.warning("backend returned HTTP %s for %s", response.status, path)
        except urllib.error.HTTPError as error:
            # A 4xx is our bug, not a transport problem: queueing and retrying a
            # malformed payload forever would just hide it.
            if 400 <= error.code < 500:
                logger.error("backend rejected %s with HTTP %s -- not retrying", path, error.code)
                self._reachable = True
                return True
            logger.warning("backend error %s for %s", error.code, path)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            logger.debug("backend unreachable (%s); queueing", error)

        self._reachable = False
        return False


@dataclass
class NullBackendClient:
    """Stand-in when the relay runs with no backend configured."""

    reachable: bool = True
    pending: int = 0

    def report_alert(self, alert_payload: dict[str, Any]) -> bool:  # noqa: ARG002
        return True

    def report_heartbeat(self, dog_id: str, relay_id: str, open_alerts: int) -> bool:  # noqa: ARG002
        return True

    def report_suppressed(self, detection: dict[str, Any], reason: str) -> bool:  # noqa: ARG002
        return True

    def flush(self) -> int:
        return 0

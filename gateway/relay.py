"""The relay node: what the owner's phone does.

Sits between the collar and the caregiver backend.  It receives verified
detections over BLE, runs the escalation ladder locally, and mirrors every state
change to the backend for the caregiver's records.

Why the ladder runs *here* and not in the cloud
-----------------------------------------------
The alert matters most in exactly the conditions where connectivity is worst:
at home at night, in a rural area, on a dead battery.  A cloud-arbitrated
escalation adds a dependency on the network to a safety path that does not need
one -- the owner's acknowledgement is a local interaction and the caregiver page
goes out over SMS.  The backend still runs its own watchdog (see
``docs/04-escalation-protocol.md``) to cover the case where the phone itself
dies, so the two are redundant rather than sequential.

Transports
----------
``--source ble`` uses the ``bleak`` library if it is installed.  ``--source
stdin`` reads newline-delimited JSON detections, which is what the replay
harness and the integration tests use, and what makes the whole relay testable
without hardware.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from escalation import (
    Channel,
    Contact,
    DetectionEvent,
    EscalationEngine,
    EscalationPolicy,
    Location,
    Notifier,
    ConsoleNotifier,
    RetryingNotifier,
)

from gateway.backend_client import BackendClient, NullBackendClient

logger = logging.getLogger("relay")

#: BLE GATT identifiers, matching firmware/collar/collar.ino.
ALERT_SERVICE_UUID = "6f1d0001-b5a3-f393-e0a9-e50e24dcca9e"
ALERT_CHAR_UUID = "6f1d0002-b5a3-f393-e0a9-e50e24dcca9e"
STATUS_CHAR_UUID = "6f1d0003-b5a3-f393-e0a9-e50e24dcca9e"


# --------------------------------------------------------------------------- #
# configuration
# --------------------------------------------------------------------------- #
def load_config(path: Path) -> dict:
    """Read the relay configuration.

    Kept as a plain JSON file rather than command-line flags because it holds
    the caregiver and emergency contact details, which should not end up in a
    shell history or a process listing.
    """
    with path.open() as handle:
        config = json.load(handle)

    for key in ("dog_id", "owner"):
        if key not in config:
            raise ValueError(f"config is missing required key {key!r}")
    return config


def build_policy(config: dict) -> EscalationPolicy:
    def contacts(entries, channel: Channel) -> tuple[Contact, ...]:
        return tuple(
            Contact(
                contact_id=entry["id"],
                name=entry["name"],
                channel=channel,
                address=entry["address"],
            )
            for entry in entries
        )

    owner_entry = config["owner"]
    owner = Contact(
        contact_id=owner_entry["id"],
        name=owner_entry["name"],
        channel=Channel.OWNER,
        address=owner_entry["address"],
    )

    timing = config.get("timing", {})
    return EscalationPolicy(
        owner=owner,
        caregivers=contacts(config.get("caregivers", []), Channel.CAREGIVER),
        emergency=contacts(config.get("emergency", []), Channel.EMERGENCY),
        owner_name=owner_entry["name"],
        owner_ack_seconds=float(timing.get("owner_ack_seconds", 60.0)),
        caregiver_ack_seconds=float(timing.get("caregiver_ack_seconds", 120.0)),
        max_location_age_seconds=float(timing.get("max_location_age_seconds", 300.0)),
        min_confidence=float(config.get("min_confidence", 0.0)),
    )


# --------------------------------------------------------------------------- #
# location
# --------------------------------------------------------------------------- #
@dataclass
class LocationProvider:
    """Supplies the most recent GPS fix.

    On a real handset this wraps the platform location API.  Here it holds
    whatever was last pushed in, and ages it against the relay's clock -- which
    is the behaviour that matters, because the engine drops fixes that are too
    old to be worth sending.
    """

    clock: Callable[[], float]
    _latitude: float | None = None
    _longitude: float | None = None
    _accuracy_m: float = 0.0
    _fixed_at: float | None = None

    def update(self, latitude: float, longitude: float, accuracy_m: float) -> None:
        self._latitude = latitude
        self._longitude = longitude
        self._accuracy_m = accuracy_m
        self._fixed_at = self.clock()

    def current(self) -> Location | None:
        if self._latitude is None or self._fixed_at is None:
            return None
        return Location(
            latitude=self._latitude,
            longitude=self._longitude,
            accuracy_m=self._accuracy_m,
            age_seconds=max(0.0, self.clock() - self._fixed_at),
        )


# --------------------------------------------------------------------------- #
# the relay
# --------------------------------------------------------------------------- #
@dataclass
class Relay:
    """Wires a detection source to the escalation engine and the backend."""

    policy: EscalationPolicy
    notifier: Notifier
    backend: BackendClient | NullBackendClient
    clock: Callable[[], float] = time.monotonic
    relay_id: str = "relay-1"
    heartbeat_seconds: float = 15.0

    def __post_init__(self) -> None:
        self.location = LocationProvider(clock=self.clock)
        self.engine = EscalationEngine(
            policy=self.policy,
            notifier=self.notifier,
            clock=self.clock,
            on_transition=self._mirror,
            on_suppressed=self._mirror_suppressed,
        )
        self._last_heartbeat = 0.0

    # -- backend mirroring -------------------------------------------------- #
    def _mirror(self, alert) -> None:
        self.backend.report_alert(alert.as_dict())

    def _mirror_suppressed(self, detection: DetectionEvent, reason: str) -> None:
        self.backend.report_suppressed(
            {
                "dog_id": detection.dog_id,
                "sequence": detection.sequence,
                "confidence": detection.confidence,
            },
            reason,
        )

    # -- driving ------------------------------------------------------------ #
    def handle_detection(self, payload: dict):
        """Accept one detection packet from the collar."""
        try:
            detection = DetectionEvent(
                dog_id=payload["dog_id"],
                sequence=int(payload["sequence"]),
                device_uptime_ms=int(payload["device_uptime_ms"]),
                confidence=float(payload["confidence"]),
                votes=int(payload.get("votes", 0)),
                window_count=int(payload.get("window_count", 0)),
                firmware_version=str(payload.get("firmware_version", "unknown")),
            )
        except (KeyError, TypeError, ValueError) as error:
            # A malformed packet is a bug in the collar or a corrupted BLE
            # frame.  Neither is a reason to take down the relay that is holding
            # other alerts open.
            logger.error("discarding malformed detection %r: %s", payload, error)
            return None

        return self.engine.submit(detection, self.location.current())

    def tick(self) -> None:
        """Advance timers and keep the backend informed."""
        self.engine.tick()

        now = self.clock()
        if now - self._last_heartbeat >= self.heartbeat_seconds:
            self._last_heartbeat = now
            self.backend.report_heartbeat(
                dog_id=self.policy.owner.contact_id,
                relay_id=self.relay_id,
                open_alerts=len(self.engine.open_alerts()),
            )
        if self.backend.pending:
            self.backend.flush()

    def acknowledge(self, alert_id: str, by: Channel = Channel.OWNER):
        return self.engine.acknowledge(alert_id, by)

    def dismiss(self, alert_id: str):
        return self.engine.dismiss(alert_id)


# --------------------------------------------------------------------------- #
# transports
# --------------------------------------------------------------------------- #
def stdin_detections(stream=sys.stdin) -> Iterator[dict]:
    """Newline-delimited JSON detections.

    Blank lines are ignored; a control line ``{"command": ...}`` is passed
    through so the caller can drive acknowledgements in a scripted run.
    """
    for line in stream:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            logger.error("ignoring non-JSON input line: %s", line[:120])


def run_stdin(relay: Relay) -> int:
    """Read detections and commands from stdin until EOF."""
    print("relay ready; send detections as JSON lines (Ctrl-D to stop)", file=sys.stderr)
    for message in stdin_detections():
        if "command" in message:
            command = message["command"]
            alert_id = message.get("alert_id")
            if command == "ack":
                relay.acknowledge(alert_id, Channel(message.get("by", "OWNER")))
            elif command == "dismiss":
                relay.dismiss(alert_id)
            elif command == "location":
                relay.location.update(
                    message["latitude"], message["longitude"], message.get("accuracy_m", 10.0)
                )
            elif command == "tick":
                relay.tick()
            else:
                logger.error("unknown command %r", command)
        else:
            relay.handle_detection(message)
        relay.tick()

    relay.tick()
    return 0


def run_ble(relay: Relay, address: str | None) -> int:
    """Subscribe to the collar's alert characteristic over BLE."""
    try:
        import asyncio

        from bleak import BleakClient, BleakScanner
    except ImportError:
        print(
            "BLE mode needs the 'bleak' package:  pip install bleak\n"
            "For a hardware-free run use:  --source stdin",
            file=sys.stderr,
        )
        return 2

    async def main() -> int:
        target = address
        if target is None:
            print("scanning for a collar ...", file=sys.stderr)
            devices = await BleakScanner.discover(timeout=8.0)
            for device in devices:
                if device.name and device.name.startswith("AssistDogCollar"):
                    target = device.address
                    print(f"found {device.name} at {target}", file=sys.stderr)
                    break
        if target is None:
            print("no collar found; is it powered and advertising?", file=sys.stderr)
            return 1

        def on_alert(_characteristic, data: bytearray) -> None:
            try:
                payload = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                logger.error("undecodable BLE payload of %d bytes", len(data))
                return
            alert = relay.handle_detection(payload)
            if alert is not None:
                # Tell the collar to stop retransmitting; it has no other way to
                # learn that the phone took responsibility.
                asyncio.create_task(
                    client.write_gatt_char(ALERT_CHAR_UUID, f"ACK:{alert.alert_id}".encode())
                )

        async with BleakClient(target) as client:
            await client.start_notify(ALERT_CHAR_UUID, on_alert)
            print("subscribed; relaying alerts (Ctrl-C to stop)", file=sys.stderr)
            while True:
                relay.tick()
                await asyncio.sleep(1.0)

    try:
        return asyncio.run(main())
    except KeyboardInterrupt:
        return 0


# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("gateway/relay_config.json"))
    parser.add_argument("--source", choices=("stdin", "ble"), default="stdin")
    parser.add_argument("--ble-address", default=None, help="skip scanning and connect directly")
    parser.add_argument("--backend", default=None, help="backend base URL, e.g. http://localhost:8080")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    if not args.config.exists():
        print(f"config not found: {args.config}", file=sys.stderr)
        print("copy gateway/relay_config.example.json and edit it", file=sys.stderr)
        return 2

    config = load_config(args.config)
    policy = build_policy(config)

    backend = (
        BackendClient(base_url=args.backend, api_key=args.api_key)
        if args.backend
        else NullBackendClient()
    )

    # Retries wrap the transport, not the ladder: a page that fails three times
    # is a failed page, and the ladder must keep running regardless.
    notifier = RetryingNotifier(
        ConsoleNotifier(sink=lambda text: print(text, flush=True)),
        max_attempts=3,
        backoff_seconds=2.0,
        sleep=time.sleep,
    )

    relay = Relay(policy=policy, notifier=notifier, backend=backend)

    if args.source == "ble":
        return run_ble(relay, args.ble_address)
    return run_stdin(relay)


if __name__ == "__main__":
    raise SystemExit(main())

"""The relay node for the IMU-Based Assistance Dog Alert system.

Receives collar detections over BLE (or stdin for replay/tests), runs the local
escalation engine, mirrors state to the backend, and exposes the browser control
API used by the owner/caregiver/emergency dashboards.

Twilio sends the predefined trial body ``sms_event_notifications``. It does not
send the engine's custom alert text.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import queue
import sys
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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

try:
    from twilio.base.exceptions import TwilioRestException
    from twilio.rest import Client
except ImportError:  # Make the error clearer at runtime if the SDK is missing.
    Client = None
    TwilioRestException = Exception

logger = logging.getLogger("relay")

# BLE GATT identifiers, matching firmware/collar/collar.ino.
ALERT_SERVICE_UUID = "6f1d0001-b5a3-f393-e0a9-e50e24dcca9e"
ALERT_CHAR_UUID = "6f1d0002-b5a3-f393-e0a9-e50e24dcca9e"
STATUS_CHAR_UUID = "6f1d0003-b5a3-f393-e0a9-e50e24dcca9e"

# Exact predefined Twilio trial template tested in the Console.
SMS_TEMPLATE = "sms_event_notifications"
DEFAULT_TWILIO_FROM_NUMBER = "+17372508034"
VOICE_TEMPLATE_URL = "https://webhooks.twilio.com/v1/Voice/Template/voice_auto_response"


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
def load_config(path: Path) -> dict:
    """Load the relay configuration."""
    with path.open(encoding="utf-8") as handle:
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
# Notifications
# --------------------------------------------------------------------------- #
class TwilioSmsNotifier:
    """Send the static template string tested in Twilio's trial console."""

    def __init__(self) -> None:
        sid = os.getenv("TWILIO_ACCOUNT_SID")
        token = os.getenv("TWILIO_AUTH_TOKEN")
        self.from_number = os.getenv(
            "TWILIO_FROM_NUMBER", DEFAULT_TWILIO_FROM_NUMBER
        )

        if Client is None:
            self.client = None
            logger.error(
                "Twilio SDK is not installed. Run: "
                ".\\.venv\\Scripts\\python.exe -m pip install twilio"
            )
        elif sid and token:
            self.client = Client(sid, token)
        else:
            self.client = None
            logger.warning(
                "Twilio credentials missing; SMS delivery will be unavailable. "
                "Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN in this terminal."
            )

    def send(self, contact, alert, message) -> bool:
        """Send only the fixed template, never the custom escalation body."""
        if self.client is None:
            logger.error("SMS not sent to %s: Twilio client is unavailable", contact.contact_id)
            return False
        if not contact.address:
            logger.error("SMS not sent: no phone number for %s", contact.contact_id)
            return False

        try:
            result = self.client.messages.create(
                to=contact.address,
                from_=self.from_number,
                body=SMS_TEMPLATE,
            )
            # API acceptance is not proof of handset delivery; Twilio's status
            # can be checked in the Console using this Message SID.
            logger.info(
                "Twilio accepted template SMS for %s; SID=%s",
                contact.contact_id,
                result.sid,
            )
            return True
        except TwilioRestException as error:
            logger.error("Twilio SMS request failed for %s: %s", contact.contact_id, error)
            return False
        except Exception:
            logger.exception("Unexpected Twilio error for %s", contact.contact_id)
            return False


class TwilioVoiceNotifier:
    """Place a call using the predefined Voice Auto Response template."""

    def __init__(self) -> None:
        sid = os.getenv("TWILIO_ACCOUNT_SID")
        token = os.getenv("TWILIO_AUTH_TOKEN")
        self.from_number = os.getenv(
            "TWILIO_FROM_NUMBER", DEFAULT_TWILIO_FROM_NUMBER
        )

        if Client is None:
            self.client = None
            logger.error(
                "Twilio SDK is not installed. Run: "
                ".\\.venv\\Scripts\\python.exe -m pip install twilio"
            )
        elif sid and token:
            self.client = Client(sid, token)
        else:
            self.client = None
            logger.warning(
                "Twilio credentials missing; voice calls will be unavailable. "
                "Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN in this terminal."
            )

    def send(self, contact, alert, message) -> bool:
        """Start the predefined voice template call; no custom spoken text."""
        if self.client is None:
            logger.error(
                "Voice call not placed to %s: Twilio client is unavailable",
                contact.contact_id,
            )
            return False
        if not contact.address:
            logger.error("Voice call not placed: no number for %s", contact.contact_id)
            return False

        try:
            call = self.client.calls.create(
                url=VOICE_TEMPLATE_URL,
                to=contact.address,
                from_=self.from_number,
            )
            logger.info(
                "Twilio accepted voice call for %s; SID=%s",
                contact.contact_id,
                call.sid,
            )
            return True
        except TwilioRestException as error:
            logger.error(
                "Twilio voice-call request failed for %s: %s",
                contact.contact_id,
                error,
            )
            return False
        except Exception:
            logger.exception("Unexpected Twilio voice error for %s", contact.contact_id)
            return False


class CombinedNotifier:
    """Log notifications, send SMS to contacts, and call the owner."""

    def __init__(
        self, console: ConsoleNotifier, sms: Notifier, voice: Notifier
    ) -> None:
        self.console = console
        self.sms = sms
        self.voice = voice

    def send(self, contact, alert, message) -> bool:
        try:
            self.console.send(contact, alert, message)
        except Exception:
            logger.exception("Console notification failed for %s", contact.contact_id)

        # Keep SMS delivery enabled for each escalation recipient.
        sms_ok = self.sms.send(contact, alert, message)

        # The initial owner receives both SMS and a call. Caregiver/emergency
        # stages retain SMS without placing an additional call to every contact.
        voice_ok = False
        if contact.channel is Channel.OWNER:
            voice_ok = self.voice.send(contact, alert, message)

        # Consider the contact reached if either real provider request succeeds.
        return sms_ok or voice_ok


# --------------------------------------------------------------------------- #
# Location
# --------------------------------------------------------------------------- #
@dataclass
class LocationProvider:
    """Store the most recent GPS fix and calculate its age."""

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
# Relay and escalation engine
# --------------------------------------------------------------------------- #
@dataclass
class Relay:
    """Connect collar detections, local escalation, and backend reporting."""

    policy: EscalationPolicy
    notifier: Notifier
    backend: BackendClient | NullBackendClient
    dog_id: str
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

    def handle_detection(self, payload: dict):
        """Validate and accept one detection packet from the collar."""
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
            logger.error("Discarding malformed detection %r: %s", payload, error)
            return None

        return self.engine.submit(detection, self.location.current())

    def tick(self) -> None:
        """Process browser responses, advance timers, and inform the backend."""
        process_control_commands(self)
        self.engine.tick()

        now = self.clock()
        if now - self._last_heartbeat >= self.heartbeat_seconds:
            self._last_heartbeat = now
            self.backend.report_heartbeat(
                dog_id=self.dog_id,
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
# Local browser control API
# --------------------------------------------------------------------------- #
_CONTROL_COMMANDS: queue.Queue[dict] = queue.Queue()
_ACTIVE_RELAY: Relay | None = None


class RelayControlHandler(BaseHTTPRequestHandler):
    """Small local HTTP API used by owner/caregiver/emergency dashboards."""

    def log_message(self, fmt, *args):
        logger.info("control-api %s - %s", self.address_string(), fmt % args)

    def _reply(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._reply(HTTPStatus.NO_CONTENT, {})

    def do_GET(self):
        if self.path == "/health":
            self._reply(HTTPStatus.OK, {"status": "UP"})
            return

        if self.path == "/api/relay/alerts":
            relay = _ACTIVE_RELAY
            if relay is None:
                self._reply(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"error": "relay not ready"},
                )
                return
            self._reply(
                HTTPStatus.OK,
                {"alerts": [a.as_dict() for a in relay.engine.history()]},
            )
            return

        self._reply(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self):
        if self.path not in ("/api/relay/ack", "/api/relay/dismiss"):
            self._reply(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 10000:
                raise ValueError("invalid request size")

            payload = json.loads(self.rfile.read(length))
            alert_id = str(payload["alert_id"])
            by = str(payload.get("by", "OWNER")).upper()
            if self.path.endswith("/ack") and by not in ("OWNER", "CAREGIVER"):
                raise ValueError("by must be OWNER or CAREGIVER")

            _CONTROL_COMMANDS.put(
                {
                    "command": "ack" if self.path.endswith("/ack") else "dismiss",
                    "alert_id": alert_id,
                    "by": by,
                }
            )
            self._reply(
                HTTPStatus.ACCEPTED,
                {"queued": True, "alert_id": alert_id},
            )
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            self._reply(HTTPStatus.BAD_REQUEST, {"error": str(exc)})


def start_control_server(relay: Relay, port: int = 8765) -> ThreadingHTTPServer:
    """Start the local control API expected by the dashboards."""
    global _ACTIVE_RELAY
    _ACTIVE_RELAY = relay
    server = ThreadingHTTPServer(("127.0.0.1", port), RelayControlHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"  role UIs control API http://127.0.0.1:{port}", file=sys.stderr)
    return server


def process_control_commands(relay: Relay) -> None:
    """Execute queued browser commands on the relay's normal driving loop."""
    while True:
        try:
            item = _CONTROL_COMMANDS.get_nowait()
        except queue.Empty:
            break
        try:
            if item["command"] == "ack":
                relay.acknowledge(item["alert_id"], Channel(item["by"]))
            else:
                relay.dismiss(item["alert_id"])
        except (KeyError, ValueError) as exc:
            logger.warning("Browser response rejected: %s", exc)


# --------------------------------------------------------------------------- #
# Transports
# --------------------------------------------------------------------------- #
def stdin_detections(stream=sys.stdin) -> Iterator[dict]:
    """Read newline-delimited JSON detections and commands."""
    for line in stream:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            logger.error("Ignoring non-JSON input line: %s", line[:120])


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
                    message["latitude"],
                    message["longitude"],
                    message.get("accuracy_m", 10.0),
                )
            elif command == "tick":
                relay.tick()
            else:
                logger.error("Unknown command %r", command)
        else:
            relay.handle_detection(message)
        relay.tick()

    relay.tick()
    return 0


def run_ble(relay: Relay, address: str | None) -> int:
    """Subscribe to the collar's alert characteristic over BLE."""
    try:
        from bleak import BleakClient, BleakScanner
    except ImportError:
        print(
            "BLE mode needs the 'bleak' library: .\\.venv\\Scripts\\python.exe "
            "-m pip install bleak\n"
            "For a hardware-free run use: --source stdin",
            file=sys.stderr,
        )
        return 2

    async def main() -> int:
        target = address
        if target is None:
            print("Scanning for a collar...", file=sys.stderr)
            devices = await BleakScanner.discover(timeout=8.0)
            for device in devices:
                if device.name and device.name.startswith("AssistDogCollar"):
                    target = device.address
                    print(f"Found {device.name} at {target}", file=sys.stderr)
                    break

        if target is None:
            print("No collar found; check that it is powered and advertising.", file=sys.stderr)
            return 1

        async with BleakClient(target) as client:
            def on_alert(_characteristic, data: bytearray) -> None:
                try:
                    payload = json.loads(data.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    logger.error("Undecodable BLE payload of %d bytes", len(data))
                    return

                alert = relay.handle_detection(payload)
                if alert is not None:
                    # Tell the collar that the relay received responsibility.
                    asyncio.create_task(
                        client.write_gatt_char(
                            ALERT_CHAR_UUID,
                            f"ACK:{alert.alert_id}".encode(),
                        )
                    )

            await client.start_notify(ALERT_CHAR_UUID, on_alert)
            print("Subscribed; relaying alerts (Ctrl-C to stop)", file=sys.stderr)
            while True:
                relay.tick()
                await asyncio.sleep(1.0)

    try:
        return asyncio.run(main())
    except KeyboardInterrupt:
        return 0


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("gateway/relay_config.json"),
    )
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
        print(f"Config not found: {args.config}", file=sys.stderr)
        print("Copy gateway/relay_config.example.json and edit it", file=sys.stderr)
        return 2

    try:
        config = load_config(args.config)
        policy = build_policy(config)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        logger.error("Could not load relay configuration: %s", error)
        return 2

    backend = (
        BackendClient(base_url=args.backend, api_key=args.api_key)
        if args.backend
        else NullBackendClient()
    )

    # Keep console output, but retries apply to the Twilio transport.
    console = ConsoleNotifier(sink=lambda text: print(text, flush=True))
    sms = RetryingNotifier(
        TwilioSmsNotifier(),
        max_attempts=3,
        backoff_seconds=2.0,
        sleep=time.sleep,
    )
    voice = TwilioVoiceNotifier()
    notifier = CombinedNotifier(console, sms, voice)

    relay = Relay(
        policy=policy,
        notifier=notifier,
        backend=backend,
        dog_id=config["dog_id"],
        relay_id=config.get("relay_id", "relay-1"),
    )

    # This local control API is required by the owner/caregiver dashboard buttons.
    try:
        control_server = start_control_server(relay)
    except OSError as error:
        logger.error(
            "Could not start dashboard control API on 127.0.0.1:8765: %s. "
            "Close any old relay process and try again.",
            error,
        )
        return 2

    try:
        if args.source == "ble":
            return run_ble(relay, args.ble_address)
        return run_stdin(relay)
    finally:
        control_server.shutdown()
        control_server.server_close()
        global _ACTIVE_RELAY
        _ACTIVE_RELAY = None


if __name__ == "__main__":
    raise SystemExit(main())

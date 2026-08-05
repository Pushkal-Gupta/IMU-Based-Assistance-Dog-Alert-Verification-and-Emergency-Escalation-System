# `gateway` — the relay node

What the owner's phone does: receives verified detections from the collar over
BLE, runs the escalation ladder locally, and mirrors every state change to the
backend.

## Why the ladder runs here

The alert matters most in exactly the conditions where connectivity is worst — at
home at night, rurally, in a basement. The owner's acknowledgement is a local
interaction and the caregiver page goes out over SMS, neither of which needs the
network. Putting the ladder in the cloud would add a dependency to a safety path
that does not need one.

The backend runs an independent watchdog for the case where this phone dies, so
the two are redundant rather than sequential. See
[../docs/02-architecture.md](../docs/02-architecture.md).

## Files

| File | Purpose |
|---|---|
| `relay.py` | The relay: BLE or stdin transport, config, escalation, heartbeats |
| `replay.py` | End-to-end harness — real IMU data through the whole pipeline |
| `backend_client.py` | Best-effort HTTP client with a bounded offline queue |
| `relay_config.example.json` | Copy to `relay_config.json` and edit |

## Replay: the integration test

```bash
python gateway/replay.py --scenario asleep
```

Streams a real recording through sliding windows, the trained classifier, the
verification gate and the escalation ladder on a simulated clock:

```
   111.2  collar: verification gate fired (2/4 windows, confidence 0.67)
   111.2  alert e5c328 -> PENDING_OWNER
   111.2  notified OWNER (owner-1) -- delivered
   171.4  alert e5c328 -> PENDING_CAREGIVER
   171.4  notified CAREGIVER (care-1) -- delivered
   292.3  alert e5c328 -> ESCALATED_EMERGENCY
   292.3  notified EMERGENCY (emerg-1) -- delivered
```

Scenarios: `responsive`, `asleep`, `delayed`, `false-alarm`.

The unit tests prove each layer in isolation; this proves they fit together, on
real motion data, with real timings.

## Running the relay

```bash
cp gateway/relay_config.example.json gateway/relay_config.json   # then edit
python gateway/relay.py --source stdin --backend http://localhost:8080
python gateway/relay.py --source ble                             # needs `pip install bleak`
```

`--source stdin` reads newline-delimited JSON detections and control commands
(`{"command":"ack","alert_id":"..."}`), which is what makes the relay testable
without hardware.

## Not a phone app

This is a Python process, not an Android or iOS app. Background execution,
doze-mode wakelocks and notification permissions are the hard part of shipping
this on a real handset, and none of it is addressed here. See
[../docs/09-limitations.md](../docs/09-limitations.md) §4.

`relay_config.json` is gitignored — it holds the real phone numbers of the people
who get paged.

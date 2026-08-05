# REST API

Base path `/api/v1`. Implemented identically by `backend/` (Jakarta EE) and
`tools/devserver.py` (development). Any divergence between them is a bug.

---

## 1. What the API is for

The relay owns the escalation ladder; the backend records what happened.

**There is deliberately no endpoint to acknowledge, escalate or resolve an
alert.** Adding one would create a second authority over the same state machine
and a race between them — one where the losing writer is a page that does or does
not go out. The backend's watchdog is the single exception, and it only ever
moves an alert forwards into a terminal state.

---

## 2. Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/alerts` | Upsert an alert (relay → backend, on every transition) |
| `GET` | `/alerts` | List alerts, newest first. `?state=` `?dog_id=` |
| `GET` | `/alerts/{alertId}` | One alert with its full audit trail |
| `POST` | `/heartbeats` | Relay liveness |
| `GET` | `/heartbeats` | Known relays and when each last reported |
| `POST` | `/detections/suppressed` | Log a detection below the confidence gate |
| `GET` | `/summary` | Aggregates for the dashboard |
| `GET` | `/health` | MicroProfile readiness (no `/api/v1` prefix) |

---

## 3. `POST /alerts`

Called on **every** state transition, not just at the end. The backend must see
`PENDING_OWNER` even if the alert resolves a second later, or the dashboard
cannot show an alert in progress.

```json
{
  "alert_id": "alert_228072cd93e5c328",
  "dog_id": "stuart",
  "raised_at_seconds": 111.23,
  "confidence": 0.67,
  "state": "PENDING_CAREGIVER",
  "escalated_by_watchdog": false,
  "owner_response_seconds": null,
  "location": {
    "latitude": 53.38620,
    "longitude": -6.25680,
    "accuracy_m": 9.0,
    "age_seconds": 6.0
  },
  "transitions": [
    { "at_seconds": 111.23, "from_state": null,
      "to_state": "PENDING_OWNER", "reason": "collar verification gate fired" },
    { "at_seconds": 171.43, "from_state": "PENDING_OWNER",
      "to_state": "PENDING_CAREGIVER",
      "reason": "owner did not respond within 60s; caregiver notified" }
  ],
  "notifications": [
    { "channel": "OWNER", "contact_id": "owner-1", "attempt": 1,
      "at_seconds": 111.23, "status": "DELIVERED", "detail": "" }
  ]
}
```

**`202 Accepted`**, not `201`. The relay has already acted; the backend is
recording a fact, not being asked to create a resource. A relay must never treat
a non-2xx here as a reason to change what it does — it queues and retries.

`400` if `alert_id` or `state` is missing, or if `location` coordinates are out
of range.

### 3.1 Idempotence

Keyed on `alert_id`, which the relay derives from
`sha256(dog_id : sequence : device_uptime_ms)`. A queue flushed after an outage,
or a BLE frame delivered twice, replays into the same row. This is what stops a
retransmission paging a caregiver twice.

### 3.2 The two clocks

`raised_at_seconds` comes from the relay's **monotonic** clock. It has **no
epoch** — it is not a Unix timestamp and must not be rendered as a date. It is
the only timebase in which the escalation intervals are meaningful, because a
wall clock that jumps mid-alert would corrupt them
([04-escalation-protocol.md §2](04-escalation-protocol.md#2-time)).

The backend stamps its own wall-clock `received_at` for retention and
cross-relay ordering. **Never subtract one from the other.**

The dashboard renders monotonic values as `t+NNN s`.

---

## 4. `POST /heartbeats`

```json
{ "dog_id": "stuart", "relay_id": "relay-1", "open_alerts": 1 }
```

Every 15 s. Silence for longer than the watchdog tolerance (60 s) **while an
alert is open** causes the backend to escalate on the relay's behalf. This is the
mechanism that covers a dead phone; see
[04-escalation-protocol.md §5](04-escalation-protocol.md#5-the-watchdog-when-the-phone-itself-dies).

`202 Accepted`. `400` if `relay_id` is missing.

---

## 5. `POST /detections/suppressed`

```json
{ "dog_id": "stuart", "sequence": 42, "confidence": 0.31,
  "reason": "confidence 0.31 below threshold 0.45" }
```

Nobody was paged, but a rising rate of near-miss detections is an early sign the
dog's alert is drifting or the collar has shifted. Worth recording.

---

## 6. `GET /summary`

```json
{
  "total_alerts": 7,
  "open_alerts": 0,
  "by_state": {
    "ACKNOWLEDGED_BY_OWNER": 4,
    "ESCALATED_EMERGENCY": 2,
    "DISMISSED_FALSE_POSITIVE": 1
  },
  "escalated": 2,
  "escalation_rate": 0.2857,
  "dismissed_false_positive": 1,
  "false_positive_rate": 0.1428,
  "suppressed_detections": 0,
  "owner_response": { "n": 4, "mean_seconds": 30.82, "max_seconds": 95.80 },
  "relays": [ { "relay_id": "relay-1", "dog_id": "stuart",
                "open_alerts": 0, "received_at": "2026-08-05T09:02:11Z" } ]
}
```

This is the system's secondary contribution. Over months, `escalation_rate`,
`false_positive_rate` and `owner_response.mean_seconds` say whether the dog's
trained alert is still reliable and whether the owner is still responding to it —
neither of which anyone can currently measure.

---

## 7. States and channels

`AlertState`: `PENDING_OWNER`, `PENDING_CAREGIVER` (open);
`ACKNOWLEDGED_BY_OWNER`, `ACKNOWLEDGED_BY_CAREGIVER`, `ESCALATED_EMERGENCY`,
`DISMISSED_FALSE_POSITIVE`, `CANCELLED` (terminal).

`Channel`: `OWNER`, `CAREGIVER`, `EMERGENCY`.
`DeliveryStatus`: `DELIVERED`, `FAILED`.

Failed attempts are stored, not discarded. "We tried to reach the caregiver and
could not" is exactly the fact an incident review needs, and it is invisible if
only successes are kept.

---

## 8. Errors

```json
{ "error": "alert_id is required", "status": 400 }
```

| Code | When |
|---|---|
| `400` | Missing required field, unknown state filter, invalid coordinates |
| `401` | API key required and absent or wrong |
| `404` | Unknown alert or path |
| `413` | Body over 1 MB |

The relay treats `4xx` as **its own** bug and drops the payload rather than
retrying forever; `5xx` and transport failures are queued and replayed in order.

---

## 9. Security

The current state is a single shared static API key in `X-API-Key`, and that is
not adequate for deployment.

Required before any real use, listed in [09-limitations.md](09-limitations.md):
per-relay identity, key rotation, TLS with certificate pinning on the relay, and
a retention policy — location and alert history are health-adjacent personal
data, and a deployment is a GDPR data controller.

Contact addresses are redacted (`******111`) wherever the alert log is shown:
vets and trainers reading the history have no business seeing a caregiver's phone
number.

---

## 10. Trying it

```bash
python tools/devserver.py --port 8080 &
python tools/seed_demo.py --backend http://localhost:8080

curl -s localhost:8080/api/v1/summary | python3 -m json.tool
curl -s "localhost:8080/api/v1/alerts?state=ESCALATED_EMERGENCY" | python3 -m json.tool
curl -s localhost:8080/health
```

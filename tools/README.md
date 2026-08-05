# `tools`

| Script | Purpose |
|---|---|
| `devserver.py` | Development stand-in for the Jakarta EE backend |
| `seed_demo.py` | Populates a backend with a realistic alert history |

## `devserver.py`

Implements the same REST contract as `backend/` ([../docs/06-api.md](../docs/06-api.md))
using only the Python standard library, backed by an append-only JSONL file.

It exists because the Java backend needs Maven and a container, which is more
than a demo or a CI job should require. The two are **not** alternatives in
production — anything one does that the other does not is a bug in one of them.

The append-only store is deliberate: this is an audit log for a safety system, and
"what did the system do, and when did it know it" is the question it has to answer
afterwards. A row is never rewritten; a state change is a new row and the latest
row per `alert_id` wins.

```bash
python tools/devserver.py                       # http://localhost:8080
python tools/devserver.py --port 9000 --api-key secret --store /tmp/alerts.jsonl
```

Serves the caregiver dashboard at `/`.

## `seed_demo.py`

```bash
python tools/devserver.py &
python tools/seed_demo.py --backend http://localhost:8080
```

Replays several *different* recordings with varying owner behaviour, so the
dashboard shows a realistic mix of answered, escalated and dismissed alerts.

It has to use different recordings: replaying the same one under different
scenarios produces the same alert id, and the backend correctly treats the repeats
as one alert. That idempotence is what stops a BLE retransmission paging a
caregiver twice — here it just means the demo needs different episodes.

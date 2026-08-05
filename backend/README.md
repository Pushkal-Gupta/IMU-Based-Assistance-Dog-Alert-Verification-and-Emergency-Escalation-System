# Caregiver backend

Jakarta EE 10 Core Profile + MicroProfile 6.1 on Open Liberty.

## What it is and is not for

The escalation ladder runs **on the owner's phone**, not here. This service is:

- the durable audit log of every alert;
- the caregiver dashboard's data source;
- the watchdog that escalates when a relay stops heartbeating with an alert open.

There is deliberately **no** endpoint to acknowledge, escalate or resolve an
alert. That would create a second authority over the same state machine and a
race between them, where the losing writer is a page that does or does not go
out. The watchdog is the single exception, and it only moves alerts forwards.

## Build and run

```bash
mvn -f backend/pom.xml package
mvn -f backend/pom.xml liberty:dev      # http://localhost:8080
```

## Status: not built

**This was never compiled.** Maven was not available in the environment this was
written in. The sources are syntax-checked with `javac` — the only errors are
unresolved `jakarta.*`, `org.eclipse.microprofile.*` and test-scope imports, as
expected without dependency resolution — but the nine watchdog tests in
`EscalationWatchdogTest` have never been executed.

For a backend you can run today, use `tools/devserver.py`, which implements the
same REST contract on the Python standard library. Any behavioural difference
between the two is a bug in one of them.

## Layout

| Package | Contents |
|---|---|
| `domain` | `AlertRecord`, `AlertState`, `Location`, `Transition`, `NotificationAttempt`, `RelayHeartbeat` — mirroring `escalation/model.py` field for field |
| `service` | `AlertRepository`, `EscalationWatchdog`, `WatchdogScheduler`, `NotificationGateway` |
| `rest` | `AlertResource` (the API), `BackendHealth` (MicroProfile readiness) |
| `config` | JAX-RS application root |

## Known gaps

- **`AlertRepository` is in-memory.** Alert history does not survive a restart.
  An audit log for a safety system must be durable; this is the first thing to
  change. The append-only JSONL store in `tools/devserver.py` is the shape it
  should take.
- **`NotificationGateway.send()` logs.** A real deployment needs an SMS provider
  with delivery receipts.
- Authentication is a single shared static API key.

See [../docs/09-limitations.md](../docs/09-limitations.md) §4.

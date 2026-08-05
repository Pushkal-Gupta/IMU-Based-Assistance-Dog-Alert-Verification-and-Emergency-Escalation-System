# Caregiver dashboard

Alert history for a caregiver, vet or trainer. One self-contained HTML file, no
build step, no dependencies.

```bash
python tools/devserver.py            # serves it at http://localhost:8080/
```

## What it shows

Per alert: when it was raised, the collar's confidence, the outcome, how long the
owner took to respond, and who was reached. Selecting a row expands the full
audit trail — every state transition with its reason, every notification attempt
with its delivery status, and the location that was sent.

Above that, five figures that are the system's secondary contribution: over
months, the escalation rate, the false-positive rate and the mean owner response
time say whether the dog's trained alert is still reliable and whether the owner
is still responding to it. Nobody can currently measure either.

## Design notes

- **Every state carries its own word.** The coloured dot reinforces the label; it
  is never the only signal. The palette is validated for colour-vision deficiency
  at all pairs (worst CVD ΔE 9.2, worst normal-vision ΔE 24.0).
- **Times render as `t+NNN s`, not as dates.** The relay clocks alerts on a
  monotonic timer with no epoch, because a wall clock that jumps mid-alert would
  corrupt the escalation intervals. Rendering a monotonic value as a date would
  be a fabrication.
- **Contact addresses are redacted.** Vets and trainers reading the history have
  no business seeing a caregiver's phone number.
- **The poll is slow (15 s) and skips unchanged data.** This is a record, not a
  monitor — the alerting path is the phone. An expanded audit trail survives a
  refresh.
- Light and dark themes both selected, not auto-inverted.

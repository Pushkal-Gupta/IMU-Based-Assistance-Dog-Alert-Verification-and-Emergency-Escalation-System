#!/usr/bin/env python3
"""Model-check every property of Escalation.tla in its own TLC run.

Each property gets a separate run so that one expected violation does not mask
the verdict on another.  Writes ``formal/results.json`` (consumed by the paper)
and keeps each run's raw TLC log under ``formal/logs/``.

    python formal/run_tlc.py            # needs Java 11+ and formal/tla2tools.jar
    make formal                         # downloads the jar if it is missing

Constants are the shipped configuration expressed in heartbeat ticks
(15 s): T1 = 60 s = 4, T2 = 120 s = 8, W = 60 s = 4.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
JAR = HERE / "tla2tools.jar"
LOGS = HERE / "logs"

TICK_SECONDS = 15
CONSTANTS = {"T1": 4, "T2": 8, "W": 4, "MaxTime": 20}

#: (property, kind, spec, caregiver configured, watchdog mode, expected to hold, meaning)
D, L = "Direct", "Ladder"
CHECKS = [
    # -- safety of the ladder itself --------------------------------------
    ("AtMostOncePerChannel", "INVARIANT", "Spec", True, D, True,
     "No channel is paged twice by the relay; the watchdog pages each channel at most once"),
    ("EmergencyOnlyAfterWindows", "INVARIANT", "Spec", True, D, True,
     "The relay pages the emergency contact only after T1 + T2 have elapsed"),
    ("EmergencyOnlyAfterWindows", "INVARIANT", "Spec", False, D, True,
     "With no caregiver configured, only after T1"),
    ("NoRelayPageAfterOwnerResponse", "INVARIANT", "Spec", True, D, True,
     "The relay never escalates after the owner responded"),
    ("BoundedResponse", "INVARIANT", "Spec", True, D, True,
     "With a live relay, every alert is closed by T1 + T2"),
    ("BoundedResponseWithWatchdog", "INVARIANT", "Spec", True, D, True,
     "If the backend knew of the alert, it is closed within T1 + T2 + W + 1 even if the relay dies"),
    ("TerminalAbsorbing", "PROPERTY", "Spec", True, D, True,
     "Relay terminal states are absorbing (a late acknowledgement does not reopen)"),
    ("BackendTerminalAbsorbing", "PROPERTY", "Spec", True, D, True,
     "Backend terminal states are absorbing"),
    # -- reliable phone and network ---------------------------------------
    ("AtMostOneEmergencyPage", "INVARIANT", "SpecReliable", True, D, True,
     "Reliable phone and network: the emergency contact is paged at most once"),
    ("NoEmergencyAfterOwnerResponse", "INVARIANT", "SpecReliable", True, D, True,
     "Reliable phone and network: no emergency page after the owner responded"),
    ("NoSilentLoss", "INVARIANT", "SpecReliable", True, D, True,
     "Reliable phone and network: no alert is silently lost"),
    ("NoPrematureEmergency", "INVARIANT", "SpecReliable", True, D, True,
     "Reliable phone and network: the caregiver tier is never skipped"),
    # -- non-vacuity witnesses (each must be reachable) -------------------
    ("NeverEmergency", "INVARIANT", "Spec", True, D, False,
     "Witness: the relay can reach ESCALATED_EMERGENCY"),
    ("NeverAckCaregiver", "INVARIANT", "Spec", True, D, False,
     "Witness: a caregiver can acknowledge"),
    ("NeverDismissed", "INVARIANT", "Spec", True, D, False,
     "Witness: the owner can dismiss"),
    ("NeverWatchdogPage", "INVARIANT", "Spec", True, D, False,
     "Witness: the watchdog can fire"),
    # -- faults: the system as built (Direct watchdog) --------------------
    ("NoPrematureEmergency", "INVARIANT", "Spec", True, D, False,
     "Under partitions: the caregiver tier is never skipped"),
    ("AtMostOneEmergencyPage", "INVARIANT", "Spec", True, D, False,
     "Under partitions: the emergency contact is paged at most once"),
    ("NoEmergencyAfterOwnerResponse", "INVARIANT", "Spec", True, D, False,
     "Under partitions / relay death: no emergency page after the owner responded"),
    ("NoSilentLoss", "INVARIANT", "Spec", True, D, False,
     "Under relay death: no alert is silently lost"),
    # -- faults: the proposed ladder-aware watchdog -----------------------
    ("NoPrematureEmergency", "INVARIANT", "Spec", True, L, True,
     "Ladder watchdog: the caregiver tier is never skipped, even under partitions"),
    ("AtMostOncePerChannel", "INVARIANT", "Spec", True, L, True,
     "Ladder watchdog: no channel paged twice by either party"),
    ("BoundedResponseWithWatchdog", "INVARIANT", "Spec", True, L, True,
     "Ladder watchdog: bounded response is preserved"),
    ("NeverWatchdogPage", "INVARIANT", "Spec", True, L, False,
     "Ladder watchdog witness: the watchdog can still reach the emergency contact"),
    ("AtMostOneEmergencyPage", "INVARIANT", "Spec", True, L, False,
     "Ladder watchdog: duplicate emergency pages remain possible (needs idempotent paging)"),
    ("NoEmergencyAfterOwnerResponse", "INVARIANT", "Spec", True, L, False,
     "Ladder watchdog: a lost acknowledgement can still cause an emergency page"),
]


def config_text(kind: str, prop: str, spec: str, caregiver: bool, mode: str) -> str:
    lines = [f"SPECIFICATION {spec}", "CONSTANTS"]
    lines += [f"    {k} = {v}" for k, v in CONSTANTS.items()]
    lines.append(f"    CaregiverConfigured = {'TRUE' if caregiver else 'FALSE'}")
    lines.append(f'    WatchdogMode = "{mode}"')
    lines.append("INVARIANT TypeOK")
    lines.append(f"{kind} {prop}")
    # The horizon ends every behaviour, which TLC would otherwise report as a
    # deadlock; it is a bound of the check, not a property of the system.
    lines.append("CHECK_DEADLOCK FALSE")
    return "\n".join(lines) + "\n"


def parse(log: str) -> dict:
    out: dict = {}
    m = re.search(r"([\d,]+) states generated, ([\d,]+) distinct states found", log)
    if m:
        out["states_generated"] = int(m.group(1).replace(",", ""))
        out["distinct_states"] = int(m.group(2).replace(",", ""))
    m = re.search(r"The depth of the complete state graph search is (\d+)", log)
    if m:
        out["depth"] = int(m.group(1))
    out["violated"] = bool(re.search(r"(Invariant|Temporal properties|Action property) .*(is )?violated", log)) or (
        "is violated" in log
    )
    out["completed"] = "Model checking completed" in log or out["violated"]
    out["error"] = None if out["completed"] else log[-2000:]
    trace = re.findall(r"^State (\d+):", log, flags=re.M)
    out["counterexample_length"] = int(trace[-1]) if (out["violated"] and trace) else None
    if out["violated"]:
        out["counterexample"] = _trace(log)
    return out


def _trace(log: str) -> list[dict]:
    """The counterexample as a list of states, keeping the variables that tell
    the story (TLC prints every variable in every state)."""
    keep = ("now", "st", "relayUp", "netUp", "synced", "bst", "lastHB", "pages", "bpages",
            "ownerAckAt", "relayEmergAt", "backendEmergAt", "careReachable")
    states = []
    for block in re.split(r"^State \d+:.*$", log, flags=re.M)[1:]:
        state = {}
        for line in block.splitlines():
            m = re.match(r"^/\\ (\w+) = (.*)$", line.strip())
            if m and m.group(1) in keep:
                state[m.group(1)] = m.group(2).strip()
        if state:
            states.append(state)
    return states


def main() -> int:
    if not JAR.exists():
        print(f"missing {JAR}; run `make formal` to download it", file=sys.stderr)
        return 2
    LOGS.mkdir(exist_ok=True)
    results = []
    for prop, kind, spec, caregiver, mode, expected, description in CHECKS:
        tag = f"{prop}_{spec}_{mode}{'' if caregiver else '_nocaregiver'}"
        cfg = LOGS / f"{tag}.cfg"
        cfg.write_text(config_text(kind, prop, spec, caregiver, mode))
        started = time.time()
        proc = subprocess.run(
            ["java", "-XX:+UseParallelGC", "-cp", str(JAR), "tlc2.TLC",
             "-workers", "auto", "-nowarning", "-noGenerateSpecTE", "-config", str(cfg),
             "-metadir", str(LOGS / f"states_{tag}"), str(HERE / "Escalation.tla")],
            capture_output=True, text=True, cwd=HERE,
        )
        log = proc.stdout + proc.stderr
        (LOGS / f"{tag}.log").write_text(log)
        parsed = parse(log)
        holds = parsed["completed"] and not parsed["violated"]
        row = {
            "property": prop,
            "kind": kind.lower(),
            "spec": spec,
            "caregiver_configured": caregiver,
            "watchdog_mode": mode,
            "description": description,
            "holds": holds,
            "expected_to_hold": expected,
            "as_expected": holds == expected,
            "seconds": round(time.time() - started, 2),
            **parsed,
        }
        results.append(row)
        verdict = "holds" if holds else ("VIOLATED" if parsed["violated"] else "ERROR")
        flag = "" if row["as_expected"] else "   <-- UNEXPECTED"
        print(f"{tag:55s} {verdict:9s} {parsed.get('distinct_states', '?'):>8} states{flag}")
        if parsed.get("error"):
            print(parsed["error"], file=sys.stderr)

    summary = {
        "tool": "TLC (tla2tools.jar)",
        "constants_ticks": CONSTANTS,
        "tick_seconds": TICK_SECONDS,
        "checks": results,
        "all_as_expected": all(r["as_expected"] for r in results),
        "max_distinct_states": max((r.get("distinct_states") or 0) for r in results),
    }
    (HERE / "results.json").write_text(json.dumps(summary, indent=2) + "\n")
    return 0 if summary["all_as_expected"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

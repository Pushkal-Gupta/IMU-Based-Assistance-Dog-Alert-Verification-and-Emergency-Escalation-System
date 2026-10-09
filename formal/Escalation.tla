----------------------------- MODULE Escalation -----------------------------
(***************************************************************************)
(* One alert episode moving through the escalation ladder of               *)
(* escalation/engine.py, together with the two things that can go wrong    *)
(* around it: the relay (the owner's phone) can die, and the network       *)
(* between the relay and the backend can partition and heal at any time.   *)
(* The backend watchdog (backend/.../EscalationWatchdog.java) escalates on *)
(* the relay's behalf when heartbeats stop while it believes an alert is   *)
(* open.                                                                   *)
(*                                                                         *)
(* Time is discrete.  One tick is one heartbeat interval (15 s in the      *)
(* shipped configuration), and T1, T2 and W are expressed in ticks.  Ticks *)
(* are "urgent": time cannot pass while a due timer, heartbeat or watchdog *)
(* sweep is pending, which models drivers that run at least once per tick. *)
(* Everything else -- the owner, the caregiver, the network, the phone     *)
(* battery -- is free to act, or not, at any moment.                       *)
(***************************************************************************)
EXTENDS Naturals

CONSTANTS
    T1,                   \* owner window, ticks
    T2,                   \* caregiver window, ticks
    W,                    \* watchdog silence tolerance, ticks
    MaxTime,              \* horizon of the bounded check
    CaregiverConfigured,  \* is a caregiver in the policy at all?
    WatchdogMode          \* "Direct": page emergency on silence (as built)
                          \* "Ladder": continue the ladder on the relay's behalf

ASSUME T1 > 0 /\ T2 > 0 /\ W > 0 /\ MaxTime > T1 + T2 + W
ASSUME WatchdogMode \in {"Direct", "Ladder"}

None     == "None"
Pending  == {"PendingOwner", "PendingCaregiver"}
Terminal == {"AckOwner", "AckCaregiver", "Emergency", "Dismissed"}
States   == Pending \cup Terminal
Channels == {"Owner", "Caregiver", "Emergency"}
Never    == MaxTime + 1          \* "this has not happened"

VARIABLES
    now,           \* the monotonic clock
    st,            \* the relay's alert state (engine.py)
    deadline,      \* deadline of the current pending stage
    pages,         \* relay notifications sent, per channel
    careReachable, \* did the caregiver page get through? (chosen once)
    ownerAckAt,    \* when the owner acknowledged or dismissed, or Never
    relayEmergAt,  \* when the relay paged the emergency contact, or Never
    relayUp,       \* is the phone alive?
    netUp,         \* can the phone reach the backend?
    synced,        \* has the backend ever heard of this alert?
    bst,           \* the backend's last-known state of the alert
    lastHB,        \* time of the last heartbeat the backend received
    bpages,        \* emergency pages sent by the watchdog
    bcare,         \* caregiver pages sent by the watchdog (Ladder mode)
    backendEmergAt \* when the watchdog paged, or Never

vars == << now, st, deadline, pages, careReachable, ownerAckAt, relayEmergAt,
           relayUp, netUp, synced, bst, lastHB, bpages, bcare, backendEmergAt >>

TypeOK ==
    /\ now \in 0..MaxTime
    /\ st \in States
    /\ pages \in [Channels -> 0..3]
    /\ careReachable \in BOOLEAN
    /\ relayUp \in BOOLEAN /\ netUp \in BOOLEAN /\ synced \in BOOLEAN
    /\ bst \in States \cup {None}
    /\ bpages \in 0..3
    /\ bcare \in 0..3

(* The collar's gate has just fired; the relay has opened the alert and paged *)
(* the owner.  The network may or may not be up at that instant.              *)
Init ==
    /\ now = 0
    /\ st = "PendingOwner"
    /\ deadline = T1
    /\ pages = [c \in Channels |-> IF c = "Owner" THEN 1 ELSE 0]
    /\ careReachable \in BOOLEAN
    /\ ownerAckAt = Never
    /\ relayEmergAt = Never
    /\ relayUp = TRUE
    /\ netUp \in BOOLEAN
    /\ synced = FALSE
    /\ bst = None
    /\ lastHB = 0
    /\ bpages = 0
    /\ bcare = 0
    /\ backendEmergAt = Never

-----------------------------------------------------------------------------
(* Obligations that must be discharged before time may pass. *)
RelayTimerDue  == relayUp /\ st \in Pending /\ now >= deadline
SyncDue        == relayUp /\ netUp /\ (~synced \/ bst # st \/ now > lastHB)
Silent         == synced /\ bst \in Pending /\ now - lastHB > W
\* Ladder mode only acts when the ladder itself would have: the caregiver at
\* T1, the emergency contact at T1 + T2 (measured from the alert).
LadderStepDue  ==
    \/ bst = "PendingOwner" /\ now >= T1
    \/ bst = "PendingCaregiver" /\ now >= T1 + T2
WatchdogDue    == Silent /\ (WatchdogMode = "Direct" \/ LadderStepDue)

Tick ==
    /\ now < MaxTime
    /\ ~RelayTimerDue /\ ~SyncDue /\ ~WatchdogDue
    /\ now' = now + 1
    /\ UNCHANGED << st, deadline, pages, careReachable, ownerAckAt, relayEmergAt,
                    relayUp, netUp, synced, bst, lastHB, bpages, bcare, backendEmergAt >>

(* engine.tick(): PENDING_OWNER -> PENDING_CAREGIVER -> ESCALATED_EMERGENCY *)
RelayTimer ==
    /\ RelayTimerDue
    /\ IF st = "PendingOwner" /\ CaregiverConfigured
         THEN /\ st' = "PendingCaregiver"
              /\ deadline' = now + T2
              /\ pages' = [pages EXCEPT !["Caregiver"] = @ + 1]
              /\ UNCHANGED relayEmergAt
         ELSE /\ st' = "Emergency"
              /\ UNCHANGED deadline
              /\ pages' = [pages EXCEPT !["Emergency"] = @ + 1]
              /\ relayEmergAt' = now
    /\ UNCHANGED << now, careReachable, ownerAckAt, relayUp, netUp, synced, bst,
                    lastHB, bpages, bcare, backendEmergAt >>

(* engine.acknowledge(OWNER) / engine.dismiss(): the owner taps the phone. *)
OwnerResponds ==
    /\ relayUp
    /\ st \in Pending
    /\ \E outcome \in {"AckOwner", "Dismissed"} : st' = outcome
    /\ ownerAckAt' = now
    /\ UNCHANGED << now, deadline, pages, careReachable, relayEmergAt, relayUp,
                    netUp, synced, bst, lastHB, bpages, bcare, backendEmergAt >>

(* engine.acknowledge(CAREGIVER): only a caregiver whose page arrived can. *)
CaregiverResponds ==
    /\ relayUp
    /\ st = "PendingCaregiver"
    /\ careReachable
    /\ st' = "AckCaregiver"
    /\ UNCHANGED << now, deadline, pages, careReachable, ownerAckAt, relayEmergAt,
                    relayUp, netUp, synced, bst, lastHB, bpages, bcare, backendEmergAt >>

(* The relay mirrors every transition and heartbeats every tick. *)
Sync ==
    /\ SyncDue
    /\ synced' = TRUE
    /\ lastHB' = now
    \* The backend never moves an alert it has already closed back to open.
    /\ bst' = IF bst \in Terminal THEN bst ELSE st
    /\ UNCHANGED << now, st, deadline, pages, careReachable, ownerAckAt,
                    relayEmergAt, relayUp, netUp, bpages, bcare, backendEmergAt >>

(* EscalationWatchdog.sweep(): relay silent beyond W while an alert is open. *)
Watchdog ==
    /\ WatchdogDue
    /\ IF WatchdogMode = "Ladder" /\ bst = "PendingOwner" /\ CaregiverConfigured
         THEN /\ bst' = "PendingCaregiver"
              /\ bcare' = bcare + 1
              /\ UNCHANGED << bpages, backendEmergAt >>
         ELSE /\ bst' = "Emergency"
              /\ bpages' = bpages + 1
              /\ backendEmergAt' = now
              /\ UNCHANGED bcare
    /\ UNCHANGED << now, st, deadline, pages, careReachable, ownerAckAt,
                    relayEmergAt, relayUp, netUp, synced, lastHB >>

RelayDies ==
    /\ relayUp
    /\ relayUp' = FALSE
    /\ UNCHANGED << now, st, deadline, pages, careReachable, ownerAckAt,
                    relayEmergAt, netUp, synced, bst, lastHB, bpages, bcare, backendEmergAt >>

NetworkFlaps ==
    /\ netUp' = ~netUp
    /\ UNCHANGED << now, st, deadline, pages, careReachable, ownerAckAt,
                    relayEmergAt, relayUp, synced, bst, lastHB, bpages, bcare, backendEmergAt >>

Next ==
    \/ Tick \/ RelayTimer \/ OwnerResponds \/ CaregiverResponds
    \/ Sync \/ Watchdog \/ RelayDies \/ NetworkFlaps

Spec == Init /\ [][Next]_vars

(* The same system with a phone that never dies and a network that never  *)
(* partitions: the configuration the relay alone is responsible for.      *)
NextReliable ==
    \/ Tick \/ RelayTimer \/ OwnerResponds \/ CaregiverResponds
    \/ Sync \/ Watchdog
ReliableInit == Init /\ netUp = TRUE
SpecReliable == ReliableInit /\ [][NextReliable]_vars

-----------------------------------------------------------------------------
(***************************************************************************)
(* Properties.  Each is checked in its own TLC run (see run_tlc.py), so a  *)
(* violation of one does not hide the verdict on another.                  *)
(***************************************************************************)

\* P1. No channel is paged twice by the relay, and the watchdog pages at most once.
AtMostOncePerChannel ==
    /\ \A c \in Channels : pages[c] <= 1
    /\ bpages <= 1
    /\ bcare <= 1

\* P2. The relay pages the emergency contact only after both windows elapsed
\*     (or, with no caregiver configured, after the owner window alone).
EmergencyOnlyAfterWindows ==
    relayEmergAt # Never =>
        relayEmergAt >= (IF CaregiverConfigured THEN T1 + T2 ELSE T1)

\* P3. The relay never pages anyone after the owner responded.
NoRelayPageAfterOwnerResponse ==
    ownerAckAt # Never => relayEmergAt = Never \/ relayEmergAt < ownerAckAt

\* P4. Bounded response with a live relay: by T1 + T2 the alert is closed.
BoundedResponse ==
    (relayUp /\ now > T1 + T2) => st \in Terminal

\* P5. If the backend knew about the alert, a dead relay cannot stall it:
\*     some party has closed it within T1 + T2 + W + 1 ticks.
BoundedResponseWithWatchdog ==
    (synced /\ now > T1 + T2 + W + 1) =>
        ((relayUp /\ st \in Terminal) \/ bst \in Terminal)

\* P5b. The caregiver tier is never skipped: no party pages the emergency
\*      contact before T1 + T2.  (Expected to FAIL in Direct mode, where a
\*      partition at the start of the alert lets the watchdog page at W + 1.)
NoPrematureEmergency ==
    /\ (relayEmergAt = Never \/ relayEmergAt >= T1 + T2)
    /\ (backendEmergAt = Never \/ backendEmergAt >= T1 + T2)

\* P6. Nobody is told twice that it is an emergency.  (Expected to FAIL:
\*     a partition with a live relay lets both the relay and the watchdog page.)
AtMostOneEmergencyPage ==
    pages["Emergency"] + bpages <= 1

\* P7. No emergency page after the owner has said they are fine.  (Expected
\*     to FAIL: the acknowledgement may never reach the backend.)
NoEmergencyAfterOwnerResponse ==
    ownerAckAt # Never =>
        /\ (relayEmergAt = Never \/ relayEmergAt < ownerAckAt)
        /\ (backendEmergAt = Never \/ backendEmergAt < ownerAckAt)

\* P8. No alert is silently lost: at the horizon, a human has either answered
\*     or been escalated to, by someone still able to act.  (Expected to FAIL:
\*     the phone can die before the backend has ever heard of the alert.)
NoSilentLoss ==
    now = MaxTime =>
        \/ ownerAckAt # Never
        \/ (relayUp /\ st \in Terminal)
        \/ bst \in Terminal
        \/ pages["Caregiver"] + pages["Emergency"] > 0

\* Witnesses.  Each is the negation of a state the system must be able to
\* reach; TLC reporting it "violated" proves the passing properties above are
\* not vacuous (e.g. P2 holding because Emergency is unreachable).
NeverEmergency      == st # "Emergency"
NeverAckCaregiver   == st # "AckCaregiver"
NeverWatchdogPage   == bpages = 0
NeverDismissed      == st # "Dismissed"

\* Action property: terminal states absorb (a late tap does not unring the bell).
TerminalAbsorbing == [][(st \in Terminal) => (st' = st)]_vars
BackendTerminalAbsorbing == [][(bst \in Terminal) => (bst' = bst)]_vars
=============================================================================

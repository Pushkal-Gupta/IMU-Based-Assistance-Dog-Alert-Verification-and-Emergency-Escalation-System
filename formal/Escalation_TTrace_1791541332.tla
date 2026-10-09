---- MODULE Escalation_TTrace_1791541332 ----
EXTENDS Sequences, TLCExt, Toolbox, Escalation, Naturals, TLC

_expression ==
    LET Escalation_TEExpression == INSTANCE Escalation_TEExpression
    IN Escalation_TEExpression!expression
----

_trace ==
    LET Escalation_TETrace == INSTANCE Escalation_TETrace
    IN Escalation_TETrace!trace
----

_inv ==
    ~(
        TLCGet("level") = Len(_TETrace)
        /\
        bcare = (0)
        /\
        ownerAckAt = (0)
        /\
        st = ("Dismissed")
        /\
        bst = ("Emergency")
        /\
        synced = (TRUE)
        /\
        netUp = (TRUE)
        /\
        lastHB = (0)
        /\
        bpages = (1)
        /\
        backendEmergAt = (5)
        /\
        pages = ([Emergency |-> 0, Owner |-> 1, Caregiver |-> 0])
        /\
        relayUp = (FALSE)
        /\
        relayEmergAt = (21)
        /\
        now = (5)
        /\
        deadline = (4)
        /\
        careReachable = (TRUE)
    )
----

_init ==
    /\ bcare = _TETrace[1].bcare
    /\ backendEmergAt = _TETrace[1].backendEmergAt
    /\ bpages = _TETrace[1].bpages
    /\ now = _TETrace[1].now
    /\ careReachable = _TETrace[1].careReachable
    /\ netUp = _TETrace[1].netUp
    /\ pages = _TETrace[1].pages
    /\ synced = _TETrace[1].synced
    /\ bst = _TETrace[1].bst
    /\ relayEmergAt = _TETrace[1].relayEmergAt
    /\ st = _TETrace[1].st
    /\ deadline = _TETrace[1].deadline
    /\ lastHB = _TETrace[1].lastHB
    /\ relayUp = _TETrace[1].relayUp
    /\ ownerAckAt = _TETrace[1].ownerAckAt
----

_next ==
    /\ \E i,j \in DOMAIN _TETrace:
        /\ \/ /\ j = i + 1
              /\ i = TLCGet("level")
        /\ bcare  = _TETrace[i].bcare
        /\ bcare' = _TETrace[j].bcare
        /\ backendEmergAt  = _TETrace[i].backendEmergAt
        /\ backendEmergAt' = _TETrace[j].backendEmergAt
        /\ bpages  = _TETrace[i].bpages
        /\ bpages' = _TETrace[j].bpages
        /\ now  = _TETrace[i].now
        /\ now' = _TETrace[j].now
        /\ careReachable  = _TETrace[i].careReachable
        /\ careReachable' = _TETrace[j].careReachable
        /\ netUp  = _TETrace[i].netUp
        /\ netUp' = _TETrace[j].netUp
        /\ pages  = _TETrace[i].pages
        /\ pages' = _TETrace[j].pages
        /\ synced  = _TETrace[i].synced
        /\ synced' = _TETrace[j].synced
        /\ bst  = _TETrace[i].bst
        /\ bst' = _TETrace[j].bst
        /\ relayEmergAt  = _TETrace[i].relayEmergAt
        /\ relayEmergAt' = _TETrace[j].relayEmergAt
        /\ st  = _TETrace[i].st
        /\ st' = _TETrace[j].st
        /\ deadline  = _TETrace[i].deadline
        /\ deadline' = _TETrace[j].deadline
        /\ lastHB  = _TETrace[i].lastHB
        /\ lastHB' = _TETrace[j].lastHB
        /\ relayUp  = _TETrace[i].relayUp
        /\ relayUp' = _TETrace[j].relayUp
        /\ ownerAckAt  = _TETrace[i].ownerAckAt
        /\ ownerAckAt' = _TETrace[j].ownerAckAt

\* Uncomment the ASSUME below to write the states of the error trace
\* to the given file in Json format. Note that you can pass any tuple
\* to `JsonSerialize`. For example, a sub-sequence of _TETrace.
    \* ASSUME
    \*     LET J == INSTANCE Json
    \*         IN J!JsonSerialize("Escalation_TTrace_1791541332.json", _TETrace)

=============================================================================

 Note that you can extract this module `Escalation_TEExpression`
  to a dedicated file to reuse `expression` (the module in the 
  dedicated `Escalation_TEExpression.tla` file takes precedence 
  over the module `Escalation_TEExpression` below).

---- MODULE Escalation_TEExpression ----
EXTENDS Sequences, TLCExt, Toolbox, Escalation, Naturals, TLC

expression == 
    [
        \* To hide variables of the `Escalation` spec from the error trace,
        \* remove the variables below.  The trace will be written in the order
        \* of the fields of this record.
        bcare |-> bcare
        ,backendEmergAt |-> backendEmergAt
        ,bpages |-> bpages
        ,now |-> now
        ,careReachable |-> careReachable
        ,netUp |-> netUp
        ,pages |-> pages
        ,synced |-> synced
        ,bst |-> bst
        ,relayEmergAt |-> relayEmergAt
        ,st |-> st
        ,deadline |-> deadline
        ,lastHB |-> lastHB
        ,relayUp |-> relayUp
        ,ownerAckAt |-> ownerAckAt
        
        \* Put additional constant-, state-, and action-level expressions here:
        \* ,_stateNumber |-> _TEPosition
        \* ,_bcareUnchanged |-> bcare = bcare'
        
        \* Format the `bcare` variable as Json value.
        \* ,_bcareJson |->
        \*     LET J == INSTANCE Json
        \*     IN J!ToJson(bcare)
        
        \* Lastly, you may build expressions over arbitrary sets of states by
        \* leveraging the _TETrace operator.  For example, this is how to
        \* count the number of times a spec variable changed up to the current
        \* state in the trace.
        \* ,_bcareModCount |->
        \*     LET F[s \in DOMAIN _TETrace] ==
        \*         IF s = 1 THEN 0
        \*         ELSE IF _TETrace[s].bcare # _TETrace[s-1].bcare
        \*             THEN 1 + F[s-1] ELSE F[s-1]
        \*     IN F[_TEPosition - 1]
    ]

=============================================================================



Parsing and semantic processing can take forever if the trace below is long.
 In this case, it is advised to uncomment the module below to deserialize the
 trace from a generated binary file.

\*
\*---- MODULE Escalation_TETrace ----
\*EXTENDS IOUtils, Escalation, TLC
\*
\*trace == IODeserialize("Escalation_TTrace_1791541332.bin", TRUE)
\*
\*=============================================================================
\*

---- MODULE Escalation_TETrace ----
EXTENDS Escalation, TLC

trace == 
    <<
    ([bcare |-> 0,ownerAckAt |-> 21,st |-> "PendingOwner",bst |-> "None",synced |-> FALSE,netUp |-> TRUE,lastHB |-> 0,bpages |-> 0,backendEmergAt |-> 21,pages |-> [Emergency |-> 0, Owner |-> 1, Caregiver |-> 0],relayUp |-> TRUE,relayEmergAt |-> 21,now |-> 0,deadline |-> 4,careReachable |-> TRUE]),
    ([bcare |-> 0,ownerAckAt |-> 21,st |-> "PendingOwner",bst |-> "PendingOwner",synced |-> TRUE,netUp |-> TRUE,lastHB |-> 0,bpages |-> 0,backendEmergAt |-> 21,pages |-> [Emergency |-> 0, Owner |-> 1, Caregiver |-> 0],relayUp |-> TRUE,relayEmergAt |-> 21,now |-> 0,deadline |-> 4,careReachable |-> TRUE]),
    ([bcare |-> 0,ownerAckAt |-> 0,st |-> "Dismissed",bst |-> "PendingOwner",synced |-> TRUE,netUp |-> TRUE,lastHB |-> 0,bpages |-> 0,backendEmergAt |-> 21,pages |-> [Emergency |-> 0, Owner |-> 1, Caregiver |-> 0],relayUp |-> TRUE,relayEmergAt |-> 21,now |-> 0,deadline |-> 4,careReachable |-> TRUE]),
    ([bcare |-> 0,ownerAckAt |-> 0,st |-> "Dismissed",bst |-> "PendingOwner",synced |-> TRUE,netUp |-> TRUE,lastHB |-> 0,bpages |-> 0,backendEmergAt |-> 21,pages |-> [Emergency |-> 0, Owner |-> 1, Caregiver |-> 0],relayUp |-> FALSE,relayEmergAt |-> 21,now |-> 0,deadline |-> 4,careReachable |-> TRUE]),
    ([bcare |-> 0,ownerAckAt |-> 0,st |-> "Dismissed",bst |-> "PendingOwner",synced |-> TRUE,netUp |-> TRUE,lastHB |-> 0,bpages |-> 0,backendEmergAt |-> 21,pages |-> [Emergency |-> 0, Owner |-> 1, Caregiver |-> 0],relayUp |-> FALSE,relayEmergAt |-> 21,now |-> 1,deadline |-> 4,careReachable |-> TRUE]),
    ([bcare |-> 0,ownerAckAt |-> 0,st |-> "Dismissed",bst |-> "PendingOwner",synced |-> TRUE,netUp |-> TRUE,lastHB |-> 0,bpages |-> 0,backendEmergAt |-> 21,pages |-> [Emergency |-> 0, Owner |-> 1, Caregiver |-> 0],relayUp |-> FALSE,relayEmergAt |-> 21,now |-> 2,deadline |-> 4,careReachable |-> TRUE]),
    ([bcare |-> 0,ownerAckAt |-> 0,st |-> "Dismissed",bst |-> "PendingOwner",synced |-> TRUE,netUp |-> TRUE,lastHB |-> 0,bpages |-> 0,backendEmergAt |-> 21,pages |-> [Emergency |-> 0, Owner |-> 1, Caregiver |-> 0],relayUp |-> FALSE,relayEmergAt |-> 21,now |-> 3,deadline |-> 4,careReachable |-> TRUE]),
    ([bcare |-> 0,ownerAckAt |-> 0,st |-> "Dismissed",bst |-> "PendingOwner",synced |-> TRUE,netUp |-> TRUE,lastHB |-> 0,bpages |-> 0,backendEmergAt |-> 21,pages |-> [Emergency |-> 0, Owner |-> 1, Caregiver |-> 0],relayUp |-> FALSE,relayEmergAt |-> 21,now |-> 4,deadline |-> 4,careReachable |-> TRUE]),
    ([bcare |-> 0,ownerAckAt |-> 0,st |-> "Dismissed",bst |-> "PendingOwner",synced |-> TRUE,netUp |-> TRUE,lastHB |-> 0,bpages |-> 0,backendEmergAt |-> 21,pages |-> [Emergency |-> 0, Owner |-> 1, Caregiver |-> 0],relayUp |-> FALSE,relayEmergAt |-> 21,now |-> 5,deadline |-> 4,careReachable |-> TRUE]),
    ([bcare |-> 0,ownerAckAt |-> 0,st |-> "Dismissed",bst |-> "Emergency",synced |-> TRUE,netUp |-> TRUE,lastHB |-> 0,bpages |-> 1,backendEmergAt |-> 5,pages |-> [Emergency |-> 0, Owner |-> 1, Caregiver |-> 0],relayUp |-> FALSE,relayEmergAt |-> 21,now |-> 5,deadline |-> 4,careReachable |-> TRUE])
    >>
----


=============================================================================

---- CONFIG Escalation_TTrace_1791541332 ----
CONSTANTS
    T1 = 4
    T2 = 8
    W = 4
    MaxTime = 20
    CaregiverConfigured = TRUE
    WatchdogMode = "Direct"

INVARIANT
    _inv

CHECK_DEADLOCK
    \* CHECK_DEADLOCK off because of PROPERTY or INVARIANT above.
    FALSE

INIT
    _init

NEXT
    _next

CONSTANT
    _TETrace <- _trace

ALIAS
    _expression
=============================================================================
\* Generated on Fri Oct 09 15:52:14 IST 2026
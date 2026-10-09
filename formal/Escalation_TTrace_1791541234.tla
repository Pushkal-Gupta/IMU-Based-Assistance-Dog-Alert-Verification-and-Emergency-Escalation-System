---- MODULE Escalation_TTrace_1791541234 ----
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
        ownerAckAt = (21)
        /\
        st = ("AckCaregiver")
        /\
        bst = ("None")
        /\
        synced = (FALSE)
        /\
        netUp = (FALSE)
        /\
        lastHB = (0)
        /\
        bpages = (0)
        /\
        backendEmergAt = (21)
        /\
        relayUp = (TRUE)
        /\
        pages = ([Emergency |-> 0, Owner |-> 1, Caregiver |-> 1])
        /\
        relayEmergAt = (21)
        /\
        now = (4)
        /\
        deadline = (12)
        /\
        careReachable = (TRUE)
    )
----

_init ==
    /\ synced = _TETrace[1].synced
    /\ now = _TETrace[1].now
    /\ lastHB = _TETrace[1].lastHB
    /\ netUp = _TETrace[1].netUp
    /\ st = _TETrace[1].st
    /\ bst = _TETrace[1].bst
    /\ backendEmergAt = _TETrace[1].backendEmergAt
    /\ bpages = _TETrace[1].bpages
    /\ relayUp = _TETrace[1].relayUp
    /\ relayEmergAt = _TETrace[1].relayEmergAt
    /\ ownerAckAt = _TETrace[1].ownerAckAt
    /\ pages = _TETrace[1].pages
    /\ deadline = _TETrace[1].deadline
    /\ careReachable = _TETrace[1].careReachable
----

_next ==
    /\ \E i,j \in DOMAIN _TETrace:
        /\ \/ /\ j = i + 1
              /\ i = TLCGet("level")
        /\ synced  = _TETrace[i].synced
        /\ synced' = _TETrace[j].synced
        /\ now  = _TETrace[i].now
        /\ now' = _TETrace[j].now
        /\ lastHB  = _TETrace[i].lastHB
        /\ lastHB' = _TETrace[j].lastHB
        /\ netUp  = _TETrace[i].netUp
        /\ netUp' = _TETrace[j].netUp
        /\ st  = _TETrace[i].st
        /\ st' = _TETrace[j].st
        /\ bst  = _TETrace[i].bst
        /\ bst' = _TETrace[j].bst
        /\ backendEmergAt  = _TETrace[i].backendEmergAt
        /\ backendEmergAt' = _TETrace[j].backendEmergAt
        /\ bpages  = _TETrace[i].bpages
        /\ bpages' = _TETrace[j].bpages
        /\ relayUp  = _TETrace[i].relayUp
        /\ relayUp' = _TETrace[j].relayUp
        /\ relayEmergAt  = _TETrace[i].relayEmergAt
        /\ relayEmergAt' = _TETrace[j].relayEmergAt
        /\ ownerAckAt  = _TETrace[i].ownerAckAt
        /\ ownerAckAt' = _TETrace[j].ownerAckAt
        /\ pages  = _TETrace[i].pages
        /\ pages' = _TETrace[j].pages
        /\ deadline  = _TETrace[i].deadline
        /\ deadline' = _TETrace[j].deadline
        /\ careReachable  = _TETrace[i].careReachable
        /\ careReachable' = _TETrace[j].careReachable

\* Uncomment the ASSUME below to write the states of the error trace
\* to the given file in Json format. Note that you can pass any tuple
\* to `JsonSerialize`. For example, a sub-sequence of _TETrace.
    \* ASSUME
    \*     LET J == INSTANCE Json
    \*         IN J!JsonSerialize("Escalation_TTrace_1791541234.json", _TETrace)

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
        synced |-> synced
        ,now |-> now
        ,lastHB |-> lastHB
        ,netUp |-> netUp
        ,st |-> st
        ,bst |-> bst
        ,backendEmergAt |-> backendEmergAt
        ,bpages |-> bpages
        ,relayUp |-> relayUp
        ,relayEmergAt |-> relayEmergAt
        ,ownerAckAt |-> ownerAckAt
        ,pages |-> pages
        ,deadline |-> deadline
        ,careReachable |-> careReachable
        
        \* Put additional constant-, state-, and action-level expressions here:
        \* ,_stateNumber |-> _TEPosition
        \* ,_syncedUnchanged |-> synced = synced'
        
        \* Format the `synced` variable as Json value.
        \* ,_syncedJson |->
        \*     LET J == INSTANCE Json
        \*     IN J!ToJson(synced)
        
        \* Lastly, you may build expressions over arbitrary sets of states by
        \* leveraging the _TETrace operator.  For example, this is how to
        \* count the number of times a spec variable changed up to the current
        \* state in the trace.
        \* ,_syncedModCount |->
        \*     LET F[s \in DOMAIN _TETrace] ==
        \*         IF s = 1 THEN 0
        \*         ELSE IF _TETrace[s].synced # _TETrace[s-1].synced
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
\*trace == IODeserialize("Escalation_TTrace_1791541234.bin", TRUE)
\*
\*=============================================================================
\*

---- MODULE Escalation_TETrace ----
EXTENDS Escalation, TLC

trace == 
    <<
    ([ownerAckAt |-> 21,st |-> "PendingOwner",bst |-> "None",synced |-> FALSE,netUp |-> FALSE,lastHB |-> 0,bpages |-> 0,backendEmergAt |-> 21,relayUp |-> TRUE,pages |-> [Emergency |-> 0, Owner |-> 1, Caregiver |-> 0],relayEmergAt |-> 21,now |-> 0,deadline |-> 4,careReachable |-> TRUE]),
    ([ownerAckAt |-> 21,st |-> "PendingOwner",bst |-> "None",synced |-> FALSE,netUp |-> FALSE,lastHB |-> 0,bpages |-> 0,backendEmergAt |-> 21,relayUp |-> TRUE,pages |-> [Emergency |-> 0, Owner |-> 1, Caregiver |-> 0],relayEmergAt |-> 21,now |-> 1,deadline |-> 4,careReachable |-> TRUE]),
    ([ownerAckAt |-> 21,st |-> "PendingOwner",bst |-> "None",synced |-> FALSE,netUp |-> FALSE,lastHB |-> 0,bpages |-> 0,backendEmergAt |-> 21,relayUp |-> TRUE,pages |-> [Emergency |-> 0, Owner |-> 1, Caregiver |-> 0],relayEmergAt |-> 21,now |-> 2,deadline |-> 4,careReachable |-> TRUE]),
    ([ownerAckAt |-> 21,st |-> "PendingOwner",bst |-> "None",synced |-> FALSE,netUp |-> FALSE,lastHB |-> 0,bpages |-> 0,backendEmergAt |-> 21,relayUp |-> TRUE,pages |-> [Emergency |-> 0, Owner |-> 1, Caregiver |-> 0],relayEmergAt |-> 21,now |-> 3,deadline |-> 4,careReachable |-> TRUE]),
    ([ownerAckAt |-> 21,st |-> "PendingOwner",bst |-> "None",synced |-> FALSE,netUp |-> FALSE,lastHB |-> 0,bpages |-> 0,backendEmergAt |-> 21,relayUp |-> TRUE,pages |-> [Emergency |-> 0, Owner |-> 1, Caregiver |-> 0],relayEmergAt |-> 21,now |-> 4,deadline |-> 4,careReachable |-> TRUE]),
    ([ownerAckAt |-> 21,st |-> "PendingCaregiver",bst |-> "None",synced |-> FALSE,netUp |-> FALSE,lastHB |-> 0,bpages |-> 0,backendEmergAt |-> 21,relayUp |-> TRUE,pages |-> [Emergency |-> 0, Owner |-> 1, Caregiver |-> 1],relayEmergAt |-> 21,now |-> 4,deadline |-> 12,careReachable |-> TRUE]),
    ([ownerAckAt |-> 21,st |-> "AckCaregiver",bst |-> "None",synced |-> FALSE,netUp |-> FALSE,lastHB |-> 0,bpages |-> 0,backendEmergAt |-> 21,relayUp |-> TRUE,pages |-> [Emergency |-> 0, Owner |-> 1, Caregiver |-> 1],relayEmergAt |-> 21,now |-> 4,deadline |-> 12,careReachable |-> TRUE])
    >>
----


=============================================================================

---- CONFIG Escalation_TTrace_1791541234 ----
CONSTANTS
    T1 = 4
    T2 = 8
    W = 4
    MaxTime = 20
    CaregiverConfigured = TRUE

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
\* Generated on Fri Oct 09 15:50:35 IST 2026
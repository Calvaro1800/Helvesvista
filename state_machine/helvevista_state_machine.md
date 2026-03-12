# HelveVista — State Machine Specification

Formal specification of the orchestration model V2.
Reference document for prototype implementation.

---

## Orchestrator States

| State | Description | Entry condition |
|-------|-------------|-----------------|
| `INIT` | Case initialized | Case creation |
| `STRUCTURED` | User input analyzed and structured | After LLM structuring |
| `CONDITIONAL_FORK` | Actor activation decided | After structuring |
| `ORCHESTRATING` | Sub-processes running in parallel | After fork |
| `AGGREGATION` | All actors terminal, results collected | All actors in terminal state |
| `USER_VALIDATION` | Awaiting user confirmation | After aggregation |
| `CLOSED_SUCCESS` | Case resolved successfully | User accepts |
| `CLOSED_ESCALATED` | Case escalated to professional | User or system escalates |
| `CLOSED_ABORTED` | Case aborted by user | User aborts |

### Orchestrator transition diagram

```
INIT
 └─► STRUCTURED
       └─► CONDITIONAL_FORK
             └─► ORCHESTRATING
                   └─► AGGREGATION          (when all actors terminal)
                         └─► USER_VALIDATION
                               ├─► CLOSED_SUCCESS
                               ├─► CLOSED_ESCALATED
                               └─► CLOSED_ABORTED
```

---

## Actor States (per institutional actor)

| State | Description |
|-------|-------------|
| `PENDING` | Activated, not yet started |
| `REQUEST_SENT` | Request dispatched to institution |
| `WAITING` | Awaiting response (timeout running) |
| `RESPONSE_RECEIVED` | Response received, version check pending |
| `CONFLICT_DETECTED` | Version check failed — stale data |
| `HITL_REQUIRED` | Human intervention required |
| `TIMEOUT` | Response deadline exceeded |
| `ESCALATED` | Terminal — retries exhausted or conflict unresolved |
| `COMPLETED` | Terminal — successfully resolved |
| `SKIPPED` | Terminal — actor not activated in conditional fork |

### Terminal states

```python
TERMINAL_ACTOR_STATES = {COMPLETED, ESCALATED, SKIPPED}
```

Aggregation is triggered when ALL actors are in a terminal state.

### Actor transition diagram

```
SKIPPED  ◄── (not activated in fork)

PENDING
 └─► REQUEST_SENT
       └─► WAITING
             ├─► RESPONSE_RECEIVED
             │     ├─► COMPLETED          (version_valid = True)
             │     └─► CONFLICT_DETECTED  (version_valid = False)
             │           └─► HITL_REQUIRED
             │                 ├─► COMPLETED   (resolve_conflict)
             │                 └─► ESCALATED   (abort_conflict)
             └─► TIMEOUT
                   ├─► WAITING            (retries remaining)
                   └─► ESCALATED          (max_retries exhausted)
```

---

## Version Checking (Safety Property)

On receiving a response from an institutional actor:

```
IF response_version >= current_event_log_version
    → version is VALID   → transition to COMPLETED
ELSE
    → version is STALE   → transition to CONFLICT_DETECTED → HITL_REQUIRED
```

**Critical implementation note:**
The version check MUST be performed against the `current_version` of the EventLog
**before** appending the `RESPONSE_RECEIVED` event.
Appending the event increments the version, which would cause a false conflict.

---

## Liveness Mechanisms

Every `WAITING` state has:
- `timeout_seconds` — maximum wait time before `TIMEOUT`
- `max_retries` — maximum number of retry cycles
- After `max_retries` exhausted → `ESCALATED` (prevents deadlock)

The `tick()` method of the orchestrator checks all active actors for timeout.
It must be called periodically in the main loop.

---

## Actors

| Actor | Role | Critical path | Optional |
|-------|------|--------------|----------|
| `OLD_PK` | Alte Pensionskasse | ✅ Yes | ❌ No |
| `NEW_PK` | Neue Pensionskasse | ✅ Yes | ❌ No |
| `AVS` | AHV-Ausgleichskasse | ❌ No | ✅ Yes |

AVS is modeled as an optional, non-critical actor (Model V2, §8).
It does not block the critical path.
It has its own independent mini state machine.

---

## Event Log Schema

Every event:

```json
{
  "event_id":   "uuid-v4",
  "case_id":    "string",
  "actor":      "ORCHESTRATOR | OLD_PK | NEW_PK | AVS",
  "event_type": "STATE_TRANSITION | CASE_INIT | ACTOR_SKIPPED | ...",
  "timestamp":  "ISO 8601 UTC",
  "version":    42,
  "payload":    { "from": "WAITING", "to": "COMPLETED", ... }
}
```

### Invariants
- Events are append-only — no modification, no deletion
- Version is monotonically increasing
- Every state change produces exactly one event
- The current state of any actor is fully reconstructible from the event log alone

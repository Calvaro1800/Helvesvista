# CLAUDE.md — HelveVista Project Configuration

This file configures Claude Code for the HelveVista prototype.
It is read automatically at the start of every Claude Code session.

---

## Project Overview

**HelveVista** is a Python prototype implementing a deterministic orchestration engine
for asynchronous multilateral interaction in the Swiss pension system.

- **Use case:** Stellenwechsel (job change requiring coordination across pension funds and AHV)
- **Method:** Design Science Research (Hevner et al., 2004)
- **Thesis:** Bachelor Thesis, ZHAW School of Management and Law
- **Author:** Christopher Alvaro

---

## Architecture Principles — CRITICAL

These principles come directly from the formal process model (V2) and must NEVER be violated.

### 1. Strict separation: Control Logic vs. LLM

```
core/     → 100% deterministic. No LLM calls. No randomness.
llm/      → LLM assistance only. Never touches state transitions.
```

**The LLM layer is ALLOWED to:**
- Structure and parse user input
- Extract structured information from documents
- Formulate user-facing messages and explanations
- Summarize case outcomes

**The LLM layer is STRICTLY FORBIDDEN to:**
- Change any state in the state machine
- Influence transition logic
- Make final decisions
- Access the event log directly

### 2. Event Log is the Source of Truth

```python
# CORRECT
state = derive_state_from_events(event_log.events)

# WRONG — never store state separately as primary source
self.current_state = new_state  # only as derived cache
```

Every state change MUST produce an immutable event in the EventLog.
The current state is always a derived view, never the primary source.

### 3. All transitions are deterministic

No probabilistic transitions. No LLM-driven routing.
A given input in a given state ALWAYS produces the same output state.

### 4. Liveness is guaranteed

Every `WAITING` state MUST have:
- A bounded timeout
- A retry count (max_retries)
- An escalation path when retries are exhausted

No state may block indefinitely.

---

## Project Structure

```
prototype/
├── core/                   # Deterministic control layer — edit carefully
│   ├── states.py           # Enums: OrchestratorState, ActorState, Actor
│   ├── event_log.py        # Append-only event log + version checking
│   ├── actor_process.py    # Mini state machine per institutional actor
│   └── orchestrator.py     # Main orchestration engine
├── llm/                    # LLM assistance layer — Claude API only
│   └── structurer.py       # Input structuring, output formulation
├── tests/
│   └── test_stellenwechsel.py  # H1 (Safety) + H2 (Liveness) validation
└── main.py                 # Entry point
```

---

## Coding Standards

### Language and style
- Python 3.11+
- Type hints on all public methods
- Docstrings on all classes and public methods
- No external dependencies beyond `anthropic` and `pytest`

### Naming conventions
```python
# States — SCREAMING_SNAKE_CASE (they are string constants / enums)
OrchestratorState.CONDITIONAL_FORK
ActorState.HITL_REQUIRED

# Classes — PascalCase
class HelveVistaOrchestrator
class ActorProcess
class EventLog

# Methods — snake_case
def send_actor_request()
def check_response_version()

# Events in the log — SCREAMING_SNAKE_CASE strings
"STATE_TRANSITION"
"VERSION_CONFLICT"
"ACTOR_SKIPPED"
```

### Error handling
```python
# CORRECT — raise ValueError for invalid transitions with clear message
def _assert_state(self, expected):
    if self._state != expected:
        raise ValueError(
            f"[{self.name}] Invalid transition: "
            f"expected={expected.value}, current={self._state.value}"
        )

# WRONG — silent failures break auditability
if self._state != expected:
    return  # BAD
```

### Adding a new state transition
1. Add the state to `core/states.py` if new
2. Implement the transition method in the appropriate class
3. Always call `self._transition(new_state, payload={...})` — never set `self._state` directly
4. Write a test scenario that exercises the transition
5. Update `state_machine/helvevista_state_machine.md`

---

## Key Domain Concepts

| Term | Definition |
|------|-----------|
| `Stellenwechsel` | Job change — the main use case. Involves alte PK, neue PK, optionally AVS |
| `Freizügigkeit` | Portability of pension assets between pension funds |
| `IK-Auszug` | Individual account statement from AHV (Individuelle Kontenauszug) |
| `Säule 2` / `BVG` | Occupational pension (2nd pillar) |
| `Säule 3a` | Private pension savings (3rd pillar, tax-advantaged) |
| `Pensionskasse (PK)` | Occupational pension fund |
| `AHV / AVS` | State pension (1st pillar) |
| `Umwandlungssatz` | Conversion rate for pension capital to annuity |
| `HITL` | Human-in-the-Loop — user intervention at conflict points |

---

## Testing Philosophy

Tests validate the formal hypotheses of the thesis:

| Hypothesis | What to test | How |
|-----------|-------------|-----|
| **H1 Safety** | Version conflict detection | Send response with `response_version < current_version` → assert `HITL_REQUIRED` |
| **H2 Liveness** | Timeout + escalation | Set `timeout_seconds=0.1`, wait, call `tick()` → assert `ESCALATED` |
| **H3 (future)** | User comprehension | Pre/post questionnaire — not in code |

Run tests:
```bash
python prototype/tests/test_stellenwechsel.py
```

All three scenarios must pass before any commit to `main`.

---

## What NOT to do

- ❌ Do not use LangGraph, AutoGen, or any agent framework — the orchestration is custom and deterministic by design
- ❌ Do not let the LLM call `orchestrator` methods directly
- ❌ Do not add async/await to the core layer without careful consideration of the determinism guarantee
- ❌ Do not store mutable state outside the EventLog as a primary source
- ❌ Do not add features not validated by a hypothesis — scope is intentionally narrow

---

## Commit Message Convention

```
feat(core): add retry mechanism to ActorProcess
fix(event_log): correct version check timing
test(h1): add version conflict scenario with AVS actor
docs: update state machine diagram
refactor(orchestrator): extract aggregation logic
```

Format: `type(scope): description`  
Types: `feat`, `fix`, `test`, `docs`, `refactor`, `chore`

---

## Claude Code Usage Notes

When working on this project with Claude Code:

1. **Always read this file first** before making changes
2. **Never modify `core/` without running the tests** after
3. For new features, ask: *does this belong in `core/` (deterministic) or `llm/` (assistance)?*
4. The EventLog is append-only — if you find yourself deleting or modifying events, something is wrong
5. The `_assert_state()` pattern is intentional — do not remove these guards

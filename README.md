# HelveVista

> **Agentic orchestration of asynchronous multilateral interaction in the Swiss pension system.**

Bachelor Thesis — ZHAW School of Management and Law  
**Author:** Christopher Alvaro  
**Supervisor:** Prof. Dr. Alexander De Spindler  
**Method:** Design Science Research (Hevner et al., 2004)

---

## Problem

The Swiss three-pillar pension system requires individuals to coordinate with multiple independent institutions simultaneously — typically a previous pension fund (alte PK), a new pension fund (neue PK), and optionally the AHV compensation office (AVS).

These actors:

- do **not** share a common database
- operate on **independent clocks** and timelines
- maintain **local, decoupled states**
- respond **asynchronously**, with varying delays

This creates a structural coordination problem that existing digital solutions — pension portals, banking apps, FAQ chatbots — cannot solve. They are siloed, reactive, and limited to a single institution's data scope.

> *The central problem is not data retrieval.  
> It is: how can a digital intermediary deterministically orchestrate asynchronous, structurally divergent institutional processes and guide them toward controlled convergence?*

---

## Core Idea

HelveVista implements a **deterministic orchestration engine** that:

- models each institutional actor as an independent **mini state machine**
- coordinates parallel asynchronous sub-processes via an **event-driven architecture**
- detects version conflicts through a **version-checking mechanism** (Safety)
- prevents deadlocks via **timeout and escalation logic** (Liveness)
- integrates **Human-in-the-Loop** conflict resolution at well-defined intervention points
- strictly separates **deterministic control logic** from **non-deterministic LLM assistance**

The LLM (Claude) is allowed to: structure input, extract information, formulate output, explain states.  
The LLM is **not** allowed to: change states, influence transitions, or make final decisions.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        User Interface                           │
└───────────────────────────┬─────────────────────────────────────┘
                            │ user input / decisions
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│              LLM Layer  (non-deterministic)                     │
│   structure │ extract │ formulate │ explain                     │
│   ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─  │
│   ✗ cannot change states  ✗ cannot decide transitions           │
└───────────────────────────┬─────────────────────────────────────┘
                            │ structured context only
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│           Deterministic Orchestration Layer  (core)             │
│                                                                 │
│   INIT → STRUCTURED → CONDITIONAL_FORK → ORCHESTRATING         │
│                              │                                  │
│              ┌───────────────┼───────────────┐                  │
│              ▼               ▼               ▼                  │
│           OLD_PK          NEW_PK          AVS (opt.)            │
│        [state machine] [state machine] [state machine]          │
│              │               │               │                  │
│              └───────────────┴───────────────┘                  │
│                              │                                  │
│                        AGGREGATION                              │
│                      USER_VALIDATION                            │
│               CLOSED_SUCCESS / ESCALATED / ABORTED             │
└───────────────────────────┬─────────────────────────────────────┘
                            │ append-only events
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Event Log  (Source of Truth)                 │
│         State = derived view    Event Log = primary source      │
└─────────────────────────────────────────────────────────────────┘
```

---

## State Machine

Each institutional actor follows the same deterministic lifecycle:

```
PENDING
  └─► REQUEST_SENT
        └─► WAITING
              ├─► RESPONSE_RECEIVED
              │     ├─► COMPLETED          (version valid)
              │     └─► CONFLICT_DETECTED
              │           └─► HITL_REQUIRED
              │                 ├─► COMPLETED   (resolved)
              │                 └─► ESCALATED   (aborted)
              └─► TIMEOUT
                    ├─► WAITING            (retry)
                    └─► ESCALATED          (retries exhausted)
```

**Safety** — No stale data is ever applied. Version conflicts trigger `CONFLICT_DETECTED` immediately.  
**Liveness** — Every `WAITING` state has a bounded timeout. No deadlocks are possible.

---

## Prototype

The prototype demonstrates the full orchestration model for the **Stellenwechsel** (job change) use case — the canonical multilateral pension coordination scenario involving up to three institutional actors.

### Running the demo

```bash
# Clone
git clone https://github.com/YOUR_USERNAME/helvevista.git
cd helvevista

# Install
pip install -r requirements.txt

# Run demo (simulated — no API key needed)
python prototype/main.py

# Run with LLM (Claude API)
export ANTHROPIC_API_KEY=sk-ant-...
python prototype/main.py
```

### Running the tests

```bash
# Validates H1 (Safety) and H2 (Liveness)
python prototype/tests/test_stellenwechsel.py
```

### Test scenarios

| Scenario | Tests | Hypothesis |
|----------|-------|------------|
| Happy Path — all actors respond in time | Full orchestration cycle | — |
| Version conflict — stale response detected | `CONFLICT_DETECTED → HITL_REQUIRED` | **H1 Safety** |
| Timeout + Escalation — actor never responds | `TIMEOUT → ESCALATED`, no deadlock | **H2 Liveness** |

---

## Repository Structure

```
helvevista/
│
├── prototype/                    # Core implementation
│   ├── core/
│   │   ├── states.py             # All states: OrchestratorState, ActorState, Actor
│   │   ├── event_log.py          # Append-only event log (Source of Truth)
│   │   ├── actor_process.py      # Mini state machine per institutional actor
│   │   └── orchestrator.py       # Main orchestration engine
│   ├── llm/
│   │   └── structurer.py         # LLM layer — Claude API (structure / formulate only)
│   ├── tests/
│   │   └── test_stellenwechsel.py # Scenario tests (H1 + H2)
│   └── main.py                   # Entry point / interactive demo
│
├── docs/
│   ├── thesis_model/             # Formal process model documentation
│   └── pension_context/          # Swiss pension system background
│
├── architecture/
│   ├── system_architecture.png   # Full system architecture diagram
│   └── control_vs_llm.png        # Control layer vs LLM separation
│
├── state_machine/
│   ├── helvevista_state_machine.md  # Formal state machine specification
│   └── diagrams/                 # State machine diagrams
│
├── diagrams/
│   ├── state_machine.png
│   ├── architecture.png
│   └── event_flow.png
│
├── notebooks/
│   └── experiments.ipynb         # Exploratory analysis and experiments
│
├── research/
│   └── literature_notes.md       # Key literature references and notes
│
├── requirements.txt
├── .gitignore
└── README.md
```

---

## Research Context

### Hypotheses validated by the prototype

| ID | Hypothesis | Method |
|----|-----------|--------|
| **H1** | A deterministic orchestration model with event-based version checking prevents the application of stale institutional data, even under asynchronous conditions. | Formal demonstration via simulated version conflicts in prototype |
| **H2** | A timeout and escalation mechanism guarantees that every activated institutional sub-process reaches either a consistent completion or explicit escalation, without permanent deadlocks. | Scenario-based tests with simulated actor non-response |
| **H3** | Users guided through their pension process by HelveVista rate their understanding of the process significantly higher after the interaction than before. | Pre/post questionnaire with 5–10 evaluation users |

### Key references

- Hevner, A. R., March, S. T., Park, J., & Ram, S. (2004). Design science in information systems research. *MIS Quarterly*, 28(1), 75–105.
- Malone, T. W., & Crowston, K. (1994). The interdisciplinary study of coordination. *ACM Computing Surveys*, 26(1), 87–119.
- Hosseini, S., & Seilani, H. (2025). The role of agentic AI in shaping a smart future. *Array*.
- Akbar, F., & Conlan, O. (2024). Towards integrating human-in-the-loop control in proactive intelligent personalised agents. *UMAP*.
- BFS / BSV (2024). Statistik der AHV 2023.
- PLV UZH (2024). Pension Literacy Studie Schweiz.

---

## Design Science Research

This prototype is developed following the **Design Science Research** methodology (Hevner et al., 2004). It constitutes an IT artifact — specifically a model and its instantiation — designed to solve a well-defined problem in a specific organizational context.

The scientific contribution lies in:
1. Formal modeling of asynchronous multilateral interaction in inter-organizational systems
2. Deterministic orchestration architecture with provable Safety and Liveness properties
3. Controlled integration of a non-deterministic AI component within a formally bounded control structure
4. Event-based case persistence enabling causal auditability

---

## Status

| Component | Status |
|-----------|--------|
| Process model V2 | ✅ Complete |
| Core state machine | ✅ Implemented |
| Event log | ✅ Implemented |
| Orchestration engine | ✅ Implemented |
| Version conflict detection (H1) | ✅ Tested |
| Timeout & escalation (H2) | ✅ Tested |
| LLM integration (Claude API) | ✅ Implemented |
| User interface | 🔄 In progress |
| H3 evaluation | 📅 Planned |

---

*Bachelor Thesis, ZHAW School of Management and Law — 2025/2026*

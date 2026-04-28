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

## Key Features

### Two active coordination scenarios

| Scenario | Actors | Description |
|----------|--------|-------------|
| **Stellenwechsel** | Alte PK · Neue PK · AVS (opt.) | Full BVG coordination for a job change |
| **Revue AVS** | AHV-Ausgleichskasse · Opt. PK | IK-Auszug review, contribution gaps, voluntary top-up |

Each scenario offers **four entry paths (A / B / C / D)**:

| Option | Title | What it does |
|--------|-------|-------------|
| **A** | Dokumente verstehen | Upload Vorsorgeausweis or IK-Auszug — Claude explains every field in plain German |
| **B** | Koordinationsverfahren einleiten | Full multi-step coordination flow with institution requests via Gmail |
| **C** | Ich weiss nicht wo anfangen | Sparring chat — user describes their situation, LLM extracts facts and recommends A/B/C/D |
| **D** | Deep-dive education | LPP-Einkauf explainer (Stellenwechsel) or AVS Nachzahlung guide (Revue AVS) |

### LLM integration points

| Where | What Claude does |
|-------|-----------------|
| **Option A** | Multimodal extraction (PDF text + image) of Vorsorgeausweis / IK-Auszug; explains four key fields |
| **Option B — Step 1** | Structures free-text situation into typed JSON context |
| **Option B — Step 2** | Generates actor-specific request emails |
| **Option B — Step 5** | **LLM-as-Judge** — evaluates each institutional response, returns structured verdict with recommendations |
| **Option C (Sparring)** | Multi-turn dialogue: extracts structured facts, synthesises situation description, recommends option |
| **Floating chat** | Context-aware FAB assistant available on every page (suppressed inside A/B/C/D which have their own chat) |

### Institution portal

A single Streamlit app supports two roles within the same session:

- **Versicherter** — guided 6-step coordination flow
- **Institution** — dashboard to view and respond to pending HelveVista requests

Institution-side features:
- Institution selector (Alte PK / Neue PK / AHV-Ausgleichskasse)
- **Multi-user case picker** — lists all active cases from MongoDB across all users
- Structured response form (actor-specific fields)
- **Document upload** — institution attaches PDF or image (e.g. Freizügigkeitsabrechnung, IK-Auszug); stored base64 in MongoDB and downloadable by the Versicherter in Step 5
- **Editable outgoing email** — pre-generated reply text can be edited before submission
- **Multi-turn clarification** (Phase 2) — institution can send a clarification request to the Versicherter; user sees an amber alert and can respond; full conversation timeline shown in Step 5

### Multi-user MongoDB persistence

- **Primary store:** MongoDB Atlas (`helvevista.cases` collection)
- **Fallback:** local `case_state.json` (used when `MONGODB_URI` is not set)
- Each case is identified by a short `case_id` and scoped to `user_email`
- `list_all_active_cases()` powers the institution's case picker across all users

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        User Interface                           │
│   Versicherter (6-step flow)  +  Institution portal             │
└───────────────────────────┬─────────────────────────────────────┘
                            │ user input / decisions
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│              LLM Layer  (non-deterministic)                     │
│   structure │ extract │ formulate │ explain │ judge             │
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
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│             MongoDB Atlas  (multi-user persistence)             │
│         Primary store ← → JSON fallback (case_state.json)      │
└─────────────────────────────────────────────────────────────────┘
```

### Tech stack

| Layer | Technology |
|-------|-----------|
| UI | Streamlit (dark navy / gold design system) |
| LLM | Anthropic Claude Sonnet (`claude-sonnet-4-20250514`) |
| Document parsing | pypdf (PDF text) + Claude vision API (images) |
| Email bridge | Gmail API via OAuth2 (`google-api-python-client`) |
| Persistence | MongoDB Atlas + local JSON fallback |
| Tests | pytest |
| Language | Python 3.11+ |

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

## Scenarios in detail

### Stellenwechsel

Canonical multilateral coordination scenario involving up to three institutional actors.

**Option A — Dokumente verstehen**  
User uploads their Vorsorgeausweis (PDF or image). Claude extracts and explains four key fields: Freizügigkeitsguthaben, Koordinationsabzug, Deckungsgrad, Umwandlungssatz. Embedded chat for follow-up questions. Educational only — no institution contact.

**Option B — Koordinationsverfahren einleiten**  
Full 6-step orchestration flow:
1. Situation beschreiben — free-text input structured by Claude into typed JSON
2. Analyse — LLM summary + actor determination
3. Akteure bestätigen — user confirms which institutions to contact
4. Koordination — requests sent (Demo: auto-simulated; Live: real Gmail)
5. Ergebnis — aggregated institutional responses with LLM-as-Judge verdict per institution
6. Entscheid — final user decision and case closure

**Option C — Sparring**  
Multi-turn guided conversation. Claude progressively extracts situation facts (employer names, dates, amounts) and generates a structured situation description. At the end, recommends one of the four options with reasoning.

**Option D — LPP-Einkauf verstehen**  
Four-section explainer: what is an LPP purchase, who benefits, tax implications, how to request a certificate. Embedded chat.

### Revue AVS

IK-Auszug review scenario.

**Option A** — Upload and explanation of the IK-Auszug (contribution years, gaps, staleness check: >12 months old is flagged).  
**Option B** — Structured coordination request to the AHV-Ausgleichskasse.  
**Option C** — Sparring flow adapted for AHV context (contribution gaps, reasons for gaps, corrective measures).  
**Option D** — Three-section guide to voluntary AVS Nachzahlung: who is affected, the 5-year time window, procedure.

---

## Institution Portal

The institution portal shares the same Streamlit app as the Versicherter view. A **"Rolle wechseln"** button in the sidebar switches between roles — intended for evaluation scenarios where a single evaluator plays both sides.

### Case picker (multi-user)

When no case is selected, the institution sees a list of all `EN_COURS` cases from MongoDB (across all registered users), sorted by last update. Each card shows: case ID, user name, scenario, requested actors, and time elapsed since the request.

### Response form

Per-institution structured fields:

| Institution | Fields |
|-------------|--------|
| Alte PK | Freizügigkeitsguthaben (CHF), Austrittsdatum, Status |
| Neue PK | Eintrittsdatum, BVG-Koordinationsabzug (CHF), BVG-Pflicht |
| AHV-Ausgleichskasse | IK-Auszug status, Beitragsjahre, Lücken |

### Document upload

Institution can attach a PDF or image (e.g. IK-Auszug, Freizügigkeitsabrechnung). The file is base64-encoded and stored in the case document in MongoDB. The Versicherter sees a download button in Step 5.

### Editable outgoing email

A pre-generated reply email (auto-populated from form fields) is shown as an editable text area before submission. The institution can adjust the wording before sending.

### Multi-turn clarification (Phase 2)

Institution can send a clarification request to the Versicherter from the dashboard. The user sees an amber action-required banner in Step 4 and Step 5. Their reply is appended to the conversation log. A full chronological timeline of all exchanges is shown in Step 5.

---

## Evaluation Methodology

### LLM-as-Judge

Each institutional response in Step 5 is evaluated by Claude in its role as a neutral quality checker. The verdict follows the format defined in the SwissText 2026 submission:

```
✅ [What was confirmed]
📅 [Deadlines or dates, if present]
⚠️  [Open points or warnings, if any]
───
URTEIL: [Dossier vollständig / Nachfrage erforderlich / Eskalation empfohlen]
→ [One concrete action recommendation]
```

The LLM-as-Judge methodology is described in detail in the associated research publication:  
[github.com/zhaw-iwi/swisstext26_pub](https://github.com/zhaw-iwi/swisstext26_pub)

### Formal hypotheses validated by the prototype

| ID | Hypothesis | Method |
|----|-----------|--------|
| **H1** | A deterministic orchestration model with event-based version checking prevents the application of stale institutional data, even under asynchronous conditions. | Formal demonstration via simulated version conflicts in prototype |
| **H2** | A timeout and escalation mechanism guarantees that every activated institutional sub-process reaches either a consistent completion or explicit escalation, without permanent deadlocks. | Scenario-based tests with simulated actor non-response |
| **H3** | Users guided through their pension process by HelveVista rate their understanding of the process significantly higher after the interaction than before. | Pre/post questionnaire with evaluation users |

### Test suite

```bash
# H1 (Safety) + H2 (Liveness) — orchestration core
python prototype/tests/test_stellenwechsel.py   # 3 scenario tests

# Unit tests — HelveVista 2.0 pure-logic functions
pytest prototype/tests/test_helvevista_2.py      # 27 tests, no LLM calls
```

| File | Tests | Covers |
|------|-------|--------|
| `test_stellenwechsel.py` | 3 | H1 Safety, H2 Liveness, happy path |
| `test_helvevista_2.py` | 27 | Document extraction, scenario cards, option configs, sparring parse, profile validation, LPP/AVS module logic |

---

## Setup & Installation

### Prerequisites

- Python 3.11+
- An Anthropic API key
- (Optional) Google OAuth2 credentials for Gmail (Live mode)
- (Optional) MongoDB Atlas connection string (multi-user persistence)

### Local setup

```bash
# Clone
git clone https://github.com/Calvaro1800/Helvesvista.git
cd Helvesvista

# Install dependencies
pip install -r requirements.txt

# Set required environment variables
export ANTHROPIC_API_KEY="sk-ant-..."

# Optional: MongoDB Atlas (falls back to local JSON if not set)
export MONGODB_URI="mongodb+srv://..."

# Run
streamlit run prototype/ui/user_app.py
```

### Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key — enables all LLM features |
| `MONGODB_URI` | No | MongoDB Atlas connection string — enables multi-user persistence; falls back to `case_state.json` |

### Gmail (Live mode)

Live mode sends real emails to institutions via Gmail OAuth2:

1. Create a Google Cloud project and enable the Gmail API
2. Download OAuth2 credentials as `credentials.json` and place it in the project root
3. On first run, a browser window opens for Gmail authentication
4. The resulting `token.json` is cached for subsequent runs

Without `credentials.json`, the app runs in **Demo mode** — institutional responses are simulated automatically after a configurable delay (default: 8 seconds), triggered by the **Simulationsmodus** toggle in the sidebar.

---

## Repository Structure

```
helvevista/
├── prototype/
│   ├── core/
│   │   ├── states.py              # OrchestratorState, ActorState, Actor
│   │   ├── event_log.py           # Append-only event log (Source of Truth)
│   │   ├── actor_process.py       # Mini state machine per institutional actor
│   │   ├── orchestrator.py        # Main orchestration engine
│   │   └── mongodb_client.py      # MongoDB Atlas client (JSON fallback)
│   ├── llm/
│   │   ├── structurer.py          # LLM layer — situation structuring, email generation
│   │   └── email_agent.py         # Gmail OAuth2 bridge
│   ├── ui/
│   │   ├── user_app.py            # Main Streamlit app — Versicherter + Institution roles
│   │   ├── hv_dashboard.py        # Scenario selection page
│   │   ├── hv_option_cards.py     # A/B/C/D option picker with status badges
│   │   ├── hv_chat.py             # Floating FAB chat assistant
│   │   ├── hv_option_chat.py      # Embedded chat for option modules
│   │   ├── hv_profile.py          # User profile form + completeness check
│   │   ├── hv_utils.py            # Document extraction via Claude API
│   │   ├── hv_styles.py           # Shared design tokens (dark navy / gold)
│   │   └── hv_options/
│   │       ├── stellenwechsel_a.py  # Vorsorgeausweis explainer
│   │       ├── stellenwechsel_c.py  # Sparring flow (Stellenwechsel)
│   │       ├── stellenwechsel_d.py  # LPP-Einkauf guide
│   │       ├── revue_avs_a.py       # IK-Auszug explainer
│   │       ├── revue_avs_b.py       # AVS coordination flow
│   │       ├── revue_avs_c.py       # Sparring flow (Revue AVS)
│   │       └── revue_avs_d.py       # AVS Nachzahlung guide
│   └── tests/
│       ├── test_stellenwechsel.py   # H1 + H2 orchestration tests (3)
│       └── test_helvevista_2.py     # HelveVista 2.0 unit tests (27)
├── docs/
│   ├── pension_context/             # Swiss pension system reference material
│   ├── thesis_model/                # Formal process model V2
│   └── superpowers/                 # Prompt engineering skills
├── state_machine/
│   └── helvevista_state_machine.md  # State machine specification
├── .streamlit/
│   └── config.toml
├── requirements.txt
├── CLAUDE.md
└── README.md
```

---

## Known Limitations

This is a research prototype, not a production system. The following limitations are intentional and documented in the thesis (Kap. 8):

- **Institutional responses are simulated.** In Demo mode, responses are generated using hardcoded plausible values (see `DEMO_RESPONSES` in `user_app.py`). Real institutional actors are not connected.
- **Gmail channel is one-directional for evaluation.** Outgoing emails are sent via a shared HelveVista Gmail account; incoming responses from real institutions are not automatically parsed.
- **No authentication system.** User login is based on name + email input only — there is no password or identity verification. Suitable for controlled evaluation only.
- **MongoDB Atlas** is optional. Without `MONGODB_URI`, all state is stored in a local `case_state.json` file, which does not support concurrent multi-user access.
- **LLM calls require a live API key.** Document extraction and all LLM-assisted features are disabled when `ANTHROPIC_API_KEY` is not set.

---

## Research Context

This prototype is developed following the **Design Science Research** methodology (Hevner et al., 2004). It constitutes an IT artifact — specifically a model and its instantiation — designed to solve a well-defined problem in a specific organizational context.

The scientific contribution lies in:
1. Formal modeling of asynchronous multilateral interaction in inter-organizational systems
2. Deterministic orchestration architecture with provable Safety and Liveness properties
3. Controlled integration of a non-deterministic AI component within a formally bounded control structure
4. Event-based case persistence enabling causal auditability
5. LLM-as-Judge evaluation methodology applied to pension coordination quality assessment

### Associated publication

The LLM-as-Judge methodology and evaluation design are described in a paper submitted to **SwissText 2026**:  
[github.com/zhaw-iwi/swisstext26_pub](https://github.com/zhaw-iwi/swisstext26_pub)

### Key references

- Hevner, A. R., March, S. T., Park, J., & Ram, S. (2004). Design science in information systems research. *MIS Quarterly*, 28(1), 75–105.
- Malone, T. W., & Crowston, K. (1994). The interdisciplinary study of coordination. *ACM Computing Surveys*, 26(1), 87–119.
- Hosseini, S., & Seilani, H. (2025). The role of agentic AI in shaping a smart future. *Array*.
- Akbar, F., & Conlan, O. (2024). Towards integrating human-in-the-loop control in proactive intelligent personalised agents. *UMAP*.
- BFS / BSV (2024). Statistik der AHV 2023.
- PLV UZH (2024). Pension Literacy Studie Schweiz.

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
| LLM integration (Claude Sonnet) | ✅ Implemented |
| Gmail OAuth2 bridge | ✅ Implemented |
| Dual-role Streamlit UI | ✅ Complete |
| Scenario: Stellenwechsel (A/B/C/D) | ✅ Complete |
| Scenario: Revue AVS (A/B/C/D) | ✅ Complete |
| Document extraction — PDF + image | ✅ Implemented |
| LLM-as-Judge verdict (Step 5) | ✅ Implemented |
| Floating chat assistant (FAB) | ✅ Implemented |
| Institution portal — case picker | ✅ Implemented |
| Institution portal — document upload | ✅ Implemented |
| Institution portal — editable email | ✅ Implemented |
| Multi-user MongoDB persistence | ✅ Implemented |
| Multi-turn clarification (Phase 2) | ✅ Implemented |
| Unit tests (27 + 3) | ✅ Complete |
| H3 evaluation | 📅 Planned (April–May 2026) |

---

*Bachelor Thesis, ZHAW School of Management and Law — 2025/2026*

# SKILL — Streamlit UI for HelveVista

## Overview

This skill defines how to build Streamlit interfaces for HelveVista.
There are two interfaces to build:
- `ui/user_app.py` — End user interface (Versicherter)
- `ui/institution_app.py` — Institution interface (OLD_PK, NEW_PK, AVS)

---

## Setup

```bash
pip install streamlit
```

Run locally:
```bash
streamlit run prototype/ui/user_app.py
streamlit run prototype/ui/institution_app.py
```

---

## Core Streamlit Patterns

### Session State — CRITICAL
Streamlit reruns the entire script on every interaction.
Use `st.session_state` to persist data between reruns.

```python
# Initialize state once
if "orchestrator" not in st.session_state:
    st.session_state.orchestrator = None
if "step" not in st.session_state:
    st.session_state.step = 1
if "activated_actors" not in st.session_state:
    st.session_state.activated_actors = []

# Access and modify
st.session_state.step += 1
```

### Step-by-step navigation
```python
def show_step(current_step: int, total_steps: int):
    st.progress(current_step / total_steps)
    st.caption(f"Schritt {current_step} von {total_steps}")

# Navigate forward
if st.button("Weiter →"):
    st.session_state.step += 1
    st.rerun()

# Navigate backward
if st.button("← Zurück"):
    st.session_state.step -= 1
    st.rerun()
```

### Status indicators
```python
def show_actor_status(actor_name: str, state: str):
    if state == "COMPLETED":
        st.success(f"✓ {actor_name} — Abgeschlossen")
    elif state == "WAITING":
        st.warning(f"⏳ {actor_name} — Wartet auf Antwort")
    elif state == "ESCALATED":
        st.error(f"✗ {actor_name} — Eskaliert")
    elif state == "SKIPPED":
        st.info(f"— {actor_name} — Nicht aktiviert")
```

### Connecting to backend
```python
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.states import Actor, ActorState, OrchestratorState
from core.orchestrator import HelveVistaOrchestrator
```

---

## User Interface — user_app.py

### Structure (6 steps)

```
Step 1: Situationsbeschreibung (Freitext)
Step 2: Fall strukturieren (LLM oder Demo)
Step 3: Akteure aktivieren (Checkboxes)
Step 4: Orchestrierung starten (live status)
Step 5: Ergebnis anzeigen (summary)
Step 6: Nutzerentscheid (accept/escalate/abort)
```

### Step 1 — Situation
```python
st.title("HelveVista — Ihre Vorsorge, einfach koordiniert")
st.subheader("Schritt 1 — Ihre Situation")
st.write("Beschreiben Sie Ihre Situation in eigenen Worten.")

situation = st.text_area(
    "Ihre Situation",
    placeholder="Beispiel: Ich wechsle meinen Job per 1. April 2025 von der Müller AG zur Novartis...",
    height=150
)

if st.button("Weiter →", disabled=not situation):
    st.session_state.raw_input = situation
    st.session_state.step = 2
    st.rerun()
```

### Step 3 — Actor selection
```python
st.subheader("Schritt 3 — Beteiligte Institutionen")
st.write("Welche Institutionen sind an Ihrem Prozess beteiligt?")

col1, col2, col3 = st.columns(3)
with col1:
    old_pk = st.checkbox("Alte Pensionskasse", value=True)
with col2:
    new_pk = st.checkbox("Neue Pensionskasse", value=True)
with col3:
    avs = st.checkbox("AHV-Ausgleichskasse", value=False)
```

### Step 4 — Live orchestration
```python
st.subheader("Schritt 4 — Koordination läuft")

# Use placeholders for live updates
status_placeholder = st.empty()

with st.spinner("HelveVista koordiniert Ihre Anfragen..."):
    for actor in activated_actors:
        # Send request
        orch.send_actor_request(actor, {...})
        # Update display
        status_placeholder.info(f"⏳ Anfrage gesendet an {actor.value}...")
        time.sleep(0.5)
        # Receive simulated response
        orch.receive_actor_response(actor, SIMULATED_RESPONSES[actor], response_version=v)
        status_placeholder.success(f"✓ {actor.value} hat geantwortet")
        time.sleep(0.3)
```

### Step 6 — User decision
```python
st.subheader("Schritt 6 — Ihr Entscheid")

col1, col2, col3 = st.columns(3)
with col1:
    if st.button("✓ Abschliessen", type="primary"):
        orch.validate_and_close("accept")
        st.session_state.final_state = "CLOSED_SUCCESS"
        st.rerun()
with col2:
    if st.button("⚠ Eskalieren"):
        orch.validate_and_close("escalate")
        st.session_state.final_state = "CLOSED_ESCALATED"
        st.rerun()
with col3:
    if st.button("✗ Abbrechen"):
        orch.validate_and_close("abort")
        st.session_state.final_state = "CLOSED_ABORTED"
        st.rerun()
```

---

## Institution Interface — institution_app.py

### Structure
```
Header: Institution name + logo placeholder
Incoming request: summary of user's situation
Response button: one-click simulation
Status: current state of the process
```

### Example
```python
st.title("HelveVista — Institutionsportal")

institution = st.selectbox(
    "Institution auswählen",
    ["Alte Pensionskasse", "Neue Pensionskasse", "AHV-Ausgleichskasse"]
)

st.divider()
st.subheader("Eingehende Anfrage")

if st.session_state.get("pending_request"):
    request = st.session_state.pending_request
    st.info(f"**Use Case:** {request['use_case']}")
    st.write(f"**Nutzeranfrage:** {request['user_summary']}")

    if st.button("✓ Anfrage beantworten", type="primary"):
        # Simulate institutional response
        st.session_state.institution_responded = True
        st.success("Antwort wurde übermittelt.")
        st.rerun()
else:
    st.write("Keine offenen Anfragen.")
```

---

## Layout Best Practices

```python
# Always set page config first
st.set_page_config(
    page_title="HelveVista",
    page_icon="🏔",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# Use columns for side-by-side content
col1, col2 = st.columns([2, 1])
with col1:
    st.write("Main content")
with col2:
    st.metric("Status", "COMPLETED", "✓")

# Use expander for technical details (Event Log)
with st.expander("Event Log anzeigen (technisch)"):
    st.json(event_log_data)

# Use divider between sections
st.divider()
```

---

## What NOT to do

- ❌ Never call `core/` methods directly from button callbacks — use session_state
- ❌ Never use `st.experimental_rerun()` — use `st.rerun()`
- ❌ Never block the UI with long operations — use `st.spinner()`
- ❌ Never mix UI logic with core/ logic — keep separation strict
- ❌ Never use st.cache for orchestrator instances — always use session_state

---

## Deployment — Streamlit Cloud

### requirements.txt
```
anthropic>=0.40.0
streamlit>=1.32.0
pytest>=8.0.0
```

### Streamlit config
Create `.streamlit/config.toml` at the root of the repo:
```toml
[server]
headless = true
port = 8501
```

### API Key — NEVER hardcode
```python
import os
api_key = os.environ.get("ANTHROPIC_API_KEY")
USE_LLM = bool(api_key)
```

On Streamlit Cloud: Settings → Secrets → add:
```
ANTHROPIC_API_KEY = "sk-..."
```

### Deploy steps
1. Push all changes to GitHub (main branch)
2. Go to share.streamlit.io
3. Connect repo: Calvaro1800/Helvesvista
4. Set main file: `prototype/ui/user_app.py`
5. Add API key in Secrets
6. Share the URL with testers

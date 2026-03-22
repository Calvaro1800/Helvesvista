# SKILL — UX/Design for HelveVista

## Overview

This skill defines the visual and UX principles for HelveVista interfaces.
Theoretical anchor: TAM (Davis, 1989) — Perceived Usefulness + Perceived Ease of Use.
Supervisor requirement: simple, pleasant, confidence-inspiring, ludic.

---

## Design Principles

### 1. Akzeptanz (TAM — Davis, 1989)
Every UI decision must serve one of two goals:
- **Perceived Usefulness** — the user understands what HelveVista does for them
- **Perceived Ease of Use** — the user never feels lost or overwhelmed

### 2. Perceived Support
The user must always feel guided. At every step:
- Show where they are in the process
- Explain what will happen next
- Confirm what has been done

### 3. Multiparty visibility
All actors (OLD_PK, NEW_PK, AVS) are always visible in one unified view.
The user sees the full picture — never just one bilateral interaction.

### 4. Longlasting
The process may span days or weeks.
The UI must communicate this naturally — not as a limitation but as a feature.

---

## Color Palette

```python
# Use these consistently across all interfaces
COLORS = {
    "primary":    "#1A3A5C",   # Deep blue — trust, institutional
    "secondary":  "#2E86AB",   # Medium blue — action, progress
    "success":    "#27AE60",   # Green — completed, positive
    "warning":    "#F39C12",   # Orange — waiting, attention needed
    "error":      "#E74C3C",   # Red — escalated, problem
    "neutral":    "#95A5A6",   # Grey — skipped, inactive
    "background": "#F8F9FA",   # Light grey — clean, professional
    "white":      "#FFFFFF",
}
```

Apply via custom CSS in Streamlit:
```python
st.markdown("""
<style>
    .main { background-color: #F8F9FA; }
    .stButton > button[kind="primary"] {
        background-color: #1A3A5C;
        color: white;
        border-radius: 8px;
    }
    .status-card {
        padding: 1rem;
        border-radius: 8px;
        margin: 0.5rem 0;
    }
</style>
""", unsafe_allow_html=True)
```

---

## Typography & Language

### Language rules for user-facing text
- Always German
- No technical terms visible to end user
- Replace: `CONDITIONAL_FORK` → `Koordination gestartet`
- Replace: `WAITING` → `Wartet auf Antwort`
- Replace: `ESCALATED` → `Weiterleitung erforderlich`
- Replace: `HITL_REQUIRED` → `Ihre Entscheidung wird benötigt`
- Replace: `Event Log` → `Protokoll` (only in expander)

### Tone
- Warm, clear, reassuring
- Short sentences
- Active voice

---

## Status Indicators

```python
STATUS_CONFIG = {
    "COMPLETED":     {"icon": "✓", "color": "success",  "label": "Abgeschlossen"},
    "WAITING":       {"icon": "⏳", "color": "warning",  "label": "Wartet auf Antwort"},
    "ESCALATED":     {"icon": "⚠", "color": "error",    "label": "Weiterleitung"},
    "HITL_REQUIRED": {"icon": "👤", "color": "warning",  "label": "Ihre Entscheidung"},
    "SKIPPED":       {"icon": "—",  "color": "neutral",  "label": "Nicht aktiviert"},
    "REQUEST":       {"icon": "📤", "color": "secondary","label": "Anfrage gesendet"},
}

def render_status_card(actor_name: str, state: str):
    config = STATUS_CONFIG.get(state, {})
    icon = config.get("icon", "?")
    label = config.get("label", state)
    st.markdown(f"""
    <div class="status-card">
        <strong>{icon} {actor_name}</strong><br>
        <span>{label}</span>
    </div>
    """, unsafe_allow_html=True)
```

---

## Progress Visualization

```python
def render_progress_bar(current_step: int, total_steps: int = 6):
    """Show progress through the 6-step process."""
    progress = current_step / total_steps
    st.progress(progress)

    steps = [
        "Situation",
        "Analyse",
        "Akteure",
        "Koordination",
        "Ergebnis",
        "Entscheid"
    ]

    cols = st.columns(total_steps)
    for i, (col, step_name) in enumerate(zip(cols, steps)):
        with col:
            if i + 1 < current_step:
                st.markdown(f"<center>✓<br><small>{step_name}</small></center>",
                           unsafe_allow_html=True)
            elif i + 1 == current_step:
                st.markdown(f"<center>●<br><small><b>{step_name}</b></small></center>",
                           unsafe_allow_html=True)
            else:
                st.markdown(f"<center>○<br><small>{step_name}</small></center>",
                           unsafe_allow_html=True)
```

---

## Metric Cards

```python
def render_summary_metrics(orch):
    """Show key metrics after orchestration."""
    actors = orch.actors
    completed = sum(1 for p in actors.values()
                   if p.state == ActorState.COMPLETED)
    total_active = sum(1 for p in actors.values()
                      if p.state != ActorState.SKIPPED)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Abgeschlossen", f"{completed}/{total_active}")
    with col2:
        st.metric("Ereignisse", orch.log.current_version)
    with col3:
        status = "Erfolgreich" if completed == total_active else "Teilweise"
        st.metric("Status", status)
```

---

## Institutional Interface Design

For institutions (OLD_PK, NEW_PK, AVS):
- Professional, clean layout
- Clear request summary in plain language
- One prominent action button: «Anfrage beantworten»
- Show deadline / urgency if applicable
- Minimal clicks — maximum 2 clicks to respond

---

## What NOT to do

- ❌ Never show raw state names (CONDITIONAL_FORK, HITL_REQUIRED) to end users
- ❌ Never use red for anything other than errors/escalations
- ❌ Never put more than one primary action button per screen
- ❌ Never use technical jargon in user-facing labels
- ❌ Never skip the progress indicator — user must always know where they are

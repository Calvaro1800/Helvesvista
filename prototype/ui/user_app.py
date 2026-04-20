"""
ui/user_app.py
--------------
HelveVista — Single Streamlit application with role switching.

Roles
-----
  Versicherter   : guided 6-step flow through Stellenwechsel coordination
  Institution    : dashboard to view and respond to pending HelveVista requests

  
Architecture (CLAUDE.md §1)
----------------------------
  - ui/ calls core/ and llm/ only — zero business logic here
  - st.session_state is the primary runtime store (orchestrator lives here)
  - case_state.json is the shared persistence layer across browser tabs
  - LLM layer: structuring + formulation only — never touches state transitions

Run
---
  streamlit run prototype/ui/user_app.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

# ── Path bootstrap ─────────────────────────────────────────────────────────────
# Adds prototype/ to sys.path so `from core.xxx` / `from llm.xxx` resolve.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

from core.orchestrator import HelveVistaOrchestrator
from core.states import Actor, ActorState, OrchestratorState
from llm.email_agent import (
    get_email_status,
    get_followup_status,
    poll_followup_inbox,
    poll_inbox,
    send_followup_email,
    send_institution_email,
)
from ui.hv_utils import extract_doc_info as _extract_doc_info


def _json_default(obj):
    if hasattr(obj, "value"):
        return obj.value
    return str(obj)


# ══════════════════════════════════════════════════════════════════════════════
# DOMAIN CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

ACTOR_LABELS: dict[Actor, str] = {
    Actor.OLD_PK: "Alte Pensionskasse",
    Actor.NEW_PK: "Neue Pensionskasse",
    Actor.AVS:    "AHV-Ausgleichskasse",
}

ACTOR_DESCRIPTIONS: dict[Actor, str] = {
    Actor.OLD_PK: (
        "Verwaltet Ihr bisheriges BVG-Guthaben und stellt "
        "die Freizügigkeitsabrechnung aus."
    ),
    Actor.NEW_PK: (
        "Übernimmt Ihr Vorsorgeguthaben und meldet Sie "
        "für die BVG-Pflicht an."
    ),
    Actor.AVS: (
        "Liefert den IK-Auszug mit Ihren AHV-Beitragsjahren "
        "(optional, nur bei Bedarf)."
    ),
}

# Deterministic fallback responses used in demo mode.
#
# Institutional responses simulated via LLM for prototype evaluation purposes.
# To be replaced by real institutional actors in production.
# See Kap. 8 of Bachelor Thesis for academic justification.
DEMO_RESPONSES: dict[Actor, dict] = {
    Actor.OLD_PK: {
        "freizuegigkeit_chf": 45_200,
        "austrittsdatum":     "31. März 2025",
        "status":             "Austritt bestätigt",
    },
    Actor.NEW_PK: {
        "eintrittsdatum":          "1. April 2025",
        "bvg_koordinationsabzug":  26_460,
        "bvg_pflicht":             True,
    },
    Actor.AVS: {
        "ik_auszug":     "verfügbar",
        "beitragsjahre": 12,
        "luecken":       0,
    },
}

# (icon, German label, badge-class suffix)
STATE_DISPLAY: dict[ActorState, tuple[str, str, str]] = {
    ActorState.PENDING:           ("·",  "Initialisiert",      "pending"),
    ActorState.REQUEST_SENT:      ("→",  "Anfrage gesendet",   "sent"),
    ActorState.WAITING:           ("◌",  "Warte auf Antwort",  "waiting"),
    ActorState.RESPONSE_RECEIVED: ("↩",  "Antwort erhalten",   "received"),
    ActorState.TIMEOUT:           ("!",  "Keine Antwort",      "timeout"),
    ActorState.CONFLICT_DETECTED: ("≠",  "Widerspruch",        "conflict"),
    ActorState.HITL_REQUIRED:     ("!",  "Eingriff nötig",     "hitl"),
    ActorState.ESCALATED:         ("↑",  "Eskaliert",          "escalated"),
    ActorState.COMPLETED:         ("✓",  "Abgeschlossen",      "completed"),
    ActorState.SKIPPED:           ("—",  "Nicht beteiligt",    "skipped"),
}

STEP_NAMES = ["Situation", "Analyse", "Akteure", "Koordination", "Ergebnis", "Entscheid"]

# How long to wait before auto-simulating institution responses (demo).
# Institutional responses simulated via LLM for prototype evaluation purposes.
# To be replaced by real institutional actors in production.
# See Kap. 8 of Bachelor Thesis for academic justification.
AUTO_SIM_DELAY = 8.0  # seconds

# Shared persistence file (both roles read/write this)
CASE_FILE  = Path(__file__).parent.parent.parent / "case_state.json"
LOGO_FILE  = Path(__file__).parent / "assets" / "logo.png"


# ══════════════════════════════════════════════════════════════════════════════
# STREAMLIT PAGE CONFIG  (must be first Streamlit call)
# ══════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="HelveVista",
    page_icon="🏔",
    layout="centered",
    initial_sidebar_state="auto",
)


# ══════════════════════════════════════════════════════════════════════════════
# DESIGN SYSTEM — Custom CSS injected once per render
# ══════════════════════════════════════════════════════════════════════════════

def _inject_css() -> None:
    st.markdown(
        """
<style>
/* ── Global ─────────────────────────────────────────────────────────────── */
html, body, [data-testid="stApp"] {
    background-color: #0F1E2E !important;
    color: #C8D8E8;
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
}

/* ── Sidebar ─────────────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background-color: #0A1520 !important;
    border-right: 1px solid #1A3048 !important;
}
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] label {
    color: #7A96B0 !important;
}

/* ── Typography ──────────────────────────────────────────────────────────── */
h1, h2, h3 {
    color: #FFFFFF !important;
    font-weight: 300 !important;
    letter-spacing: 0.03em;
}
h1 { font-size: 1.75rem !important; }
h2 { font-size: 1.3rem  !important; }
h3 { font-size: 1.05rem !important; font-weight: 400 !important; }

/* ── Primary buttons — gold ──────────────────────────────────────────────── */
.stButton > button[kind="primary"] {
    background-color: #C9A84C !important;
    color: #0F1E2E !important;
    border: none !important;
    border-radius: 3px !important;
    font-weight: 600 !important;
    letter-spacing: 0.06em !important;
}
.stButton > button[kind="primary"]:hover {
    background-color: #B8923E !important;
}

/* ── Secondary buttons ───────────────────────────────────────────────────── */
.stButton > button[kind="secondary"] {
    background-color: transparent !important;
    color: #7A96B0 !important;
    border: 1px solid #1A3048 !important;
    border-radius: 3px !important;
}
.stButton > button[kind="secondary"]:hover {
    border-color: #C9A84C !important;
    color: #C9A84C !important;
}

/* ── Text area / inputs ──────────────────────────────────────────────────── */
textarea, input[type="text"], input[type="number"] {
    background-color: #0D1B2A !important;
    color: #C8D8E8 !important;
    border: 1px solid #1A3048 !important;
    border-radius: 3px !important;
}
textarea:focus, input:focus {
    border-color: #C9A84C !important;
    box-shadow: 0 0 0 1px #C9A84C40 !important;
}

/* ── Selectbox ───────────────────────────────────────────────────────────── */
[data-testid="stSelectbox"] > div > div {
    background-color: #0D1B2A !important;
    border: 1px solid #1A3048 !important;
    color: #C8D8E8 !important;
    border-radius: 3px !important;
}

/* ── Metric cards ────────────────────────────────────────────────────────── */
[data-testid="metric-container"] {
    background-color: #122033 !important;
    border: 1px solid #1A3048 !important;
    border-radius: 6px !important;
    padding: 1rem !important;
}
[data-testid="stMetricValue"] { color: #C9A84C !important; font-weight: 400 !important; }
[data-testid="stMetricLabel"] { color: #5A7A9A !important; }

/* ── Progress bar ────────────────────────────────────────────────────────── */
[data-testid="stProgress"] > div > div { background-color: #C9A84C !important; }
[data-testid="stProgress"] > div       { background-color: #1A3048 !important; }

/* ── Bordered containers ─────────────────────────────────────────────────── */
[data-testid="stVerticalBlockBorderWrapper"] {
    background-color: #122033 !important;
    border: 1px solid #1A3048 !important;
    border-radius: 6px !important;
}

/* ── Expander ────────────────────────────────────────────────────────────── */
[data-testid="stExpander"] {
    border: 1px solid #1A3048 !important;
    border-radius: 4px !important;
    background-color: #0D1B2A !important;
}
[data-testid="stExpanderToggleIcon"] { color: #5A7A9A !important; }

/* ── Alerts ──────────────────────────────────────────────────────────────── */
[data-testid="stAlert"] { border-radius: 3px !important; }

/* ── Divider ─────────────────────────────────────────────────────────────── */
hr { border-color: #1A3048 !important; margin: 1.5rem 0 !important; }

/* ── Caption ─────────────────────────────────────────────────────────────── */
[data-testid="stCaptionContainer"] p { color: #5A7A9A !important; font-size: 0.8rem !important; }

/* ── Checkbox ────────────────────────────────────────────────────────────── */
[data-testid="stCheckbox"] label { color: #C8D8E8 !important; }
[data-testid="stCheckbox"] svg   { color: #C9A84C !important; }

/* ── Radio ───────────────────────────────────────────────────────────────── */
[data-testid="stRadio"] label { color: #C8D8E8 !important; }

/* ── Spinner ─────────────────────────────────────────────────────────────── */
[data-testid="stSpinner"] p { color: #C9A84C !important; }

/* ══ CUSTOM CLASSES ═══════════════════════════════════════════════════════ */

/* Logo — large (login) */
.hv-logo-lg {
    text-align: center;
    padding: 3rem 0 1.5rem 0;
    letter-spacing: 0.12em;
}
.hv-logo-lg .helve { color: #C9A84C; font-size: 3.5rem; font-weight: 700; }
.hv-logo-lg .vista { color: #FFFFFF;  font-size: 3.5rem; font-weight: 200; }
.hv-logo-lg .sub {
    display: block;
    color: #3E5F7A;
    font-size: 0.6rem;
    letter-spacing: 0.4em;
    margin-top: 0.5rem;
}

/* Logo — small (sidebar) */
.hv-logo-sm { text-align: center; padding: 1.2rem 0 1.5rem 0; }
.hv-logo-sm .helve { color: #C9A84C; font-size: 1.15rem; font-weight: 700; letter-spacing: 0.1em; }
.hv-logo-sm .vista { color: #FFFFFF;  font-size: 1.15rem; font-weight: 200; letter-spacing: 0.1em; }
.hv-logo-sm .sub   { display: block; color: #2E4A5E; font-size: 0.52rem; letter-spacing: 0.3em; margin-top: 0.2rem; }

/* Section label — small caps label above sections */
.hv-label {
    color: #3E5F7A;
    font-size: 0.65rem;
    letter-spacing: 0.3em;
    text-transform: uppercase;
    font-weight: 500;
    margin-bottom: 0.75rem;
}

/* Step indicator */
.hv-steps { display: flex; margin-bottom: 2rem; gap: 2px; }
.hv-step {
    flex: 1;
    text-align: center;
    font-size: 0.65rem;
    letter-spacing: 0.08em;
    color: #253A50;
    padding: 0.4rem 0.2rem;
    border-bottom: 2px solid #1A3048;
}
.hv-step.done   { color: #3A7A58; border-bottom-color: #2A5C40; }
.hv-step.active { color: #C9A84C; border-bottom-color: #C9A84C; font-weight: 600; }

/* Status badges */
.hv-badge {
    display: inline-block;
    padding: 0.18rem 0.65rem;
    border-radius: 2px;
    font-size: 0.72rem;
    font-weight: 500;
    letter-spacing: 0.03em;
    white-space: nowrap;
}
.hv-badge-completed { background:#0C2818; color:#4CAF82; border:1px solid #1A4C30; }
.hv-badge-received  { background:#0C2818; color:#4CAF82; border:1px solid #1A4C30; }
.hv-badge-waiting   { background:#1E1800; color:#C9A84C; border:1px solid #3A3000; }
.hv-badge-sent      { background:#0E1E30; color:#6AA0C8; border:1px solid #1A3A58; }
.hv-badge-pending   { background:#0F1E2E; color:#4A6A88; border:1px solid #1A3048; }
.hv-badge-timeout   { background:#201000; color:#C08040; border:1px solid #3A2000; }
.hv-badge-conflict  { background:#200A0A; color:#C06070; border:1px solid #3A1A1A; }
.hv-badge-hitl      { background:#201800; color:#D0A050; border:1px solid #3A2800; }
.hv-badge-escalated { background:#200A0A; color:#C06070; border:1px solid #3A1A1A; }
.hv-badge-skipped   { background:#141E28; color:#3A5A78; border:1px solid #1A2A38; }

/* Case ID monospace */
.hv-case-id {
    font-family: 'Courier New', monospace;
    color: #C9A84C;
    font-size: 0.8rem;
    letter-spacing: 0.12em;
}

/* Footer */
.hv-footer {
    text-align: center;
    color: #253A50;
    font-size: 0.68rem;
    letter-spacing: 0.18em;
    padding: 2.5rem 0 1rem 0;
    border-top: 1px solid #1A3048;
    margin-top: 3rem;
}

/* Confirmation icon */
.hv-confirm { text-align: center; padding: 2.5rem 0 1.5rem 0; }
.hv-confirm .icon { font-size: 2.8rem; margin-bottom: 0.5rem; }
.hv-confirm .title { color: #FFFFFF; font-size: 1.35rem; font-weight: 300; letter-spacing: 0.04em; }
.hv-confirm .sub   { color: #4A6A88; font-size: 0.85rem; margin-top: 0.4rem; }

/* ══ INSTITUTION PORTAL ════════════════════════════════════════════════════ */

/* Institution role badge — blue accent */
.hv-inst-badge {
    display: inline-block;
    padding: 0.15rem 0.55rem;
    background: #0A1E30;
    color: #2E86AB;
    border: 1px solid #1A4060;
    border-radius: 2px;
    font-size: 0.62rem;
    letter-spacing: 0.25em;
    font-weight: 500;
}

/* Email simulation card */
.hv-email-card {
    background: #162535;
    border: 1px solid #1A3A50;
    border-radius: 4px;
    padding: 1.2rem 1.4rem;
    font-size: 0.88rem;
    line-height: 1.7;
    margin-bottom: 0.8rem;
}
.hv-email-header-row {
    font-family: 'Courier New', monospace;
    font-size: 0.76rem;
    color: #4A7A9A;
    border-bottom: 1px solid #1A3048;
    padding-bottom: 0.6rem;
    margin-bottom: 0.8rem;
}
.hv-email-header-row span { color: #C8D8E8; }
.hv-email-body { color: #A0B8CC; line-height: 1.8; }
.hv-email-body p { margin: 0 0 0.6rem 0; }

/* Case timeline */
.hv-timeline { padding-left: 0.2rem; }
.hv-timeline-item {
    position: relative;
    padding: 0.25rem 0 0.25rem 1.2rem;
    border-left: 1px solid #1A3048;
    margin-bottom: 0.25rem;
}
.hv-timeline-item::before {
    content: '';
    position: absolute;
    left: -4px;
    top: 0.55rem;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #2E86AB;
}
.hv-timeline-ts    { font-size: 0.67rem; color: #2E5A78; font-family: 'Courier New', monospace; }
.hv-timeline-label { font-size: 0.8rem; color: #8AAEC8; }

/* Empty state */
.hv-empty-state { text-align: center; padding: 2.5rem 1rem; color: #2E4A5E; }
.hv-empty-state .icon { font-size: 2rem; margin-bottom: 0.8rem; }
.hv-empty-state .text { font-size: 0.88rem; letter-spacing: 0.03em; line-height: 1.7; }

/* Institution metadata row */
.hv-meta-row { margin-bottom: 0.55rem; }
.hv-meta-label {
    color: #3E5F7A;
    font-size: 0.65rem;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    font-weight: 500;
    display: block;
    margin-bottom: 0.1rem;
}
</style>
        """,
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# CASE STATE — JSON persistence shared between browser tabs / roles
# ══════════════════════════════════════════════════════════════════════════════

def _load_case() -> dict:
    """Read case_state.json. Returns {} if missing or corrupt."""
    if CASE_FILE.exists():
        try:
            with open(CASE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def _save_case(state: dict) -> None:
    """Write case_state.json (best-effort; silently swallows IO errors)."""
    # Ensure a stable case_id exists before writing
    if not st.session_state.get("case_id"):
        st.session_state.case_id = str(uuid.uuid4())[:8].upper()
    try:
        with open(CASE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except IOError:
        pass
    # Sync to MongoDB Atlas (non-blocking)
    try:
        from core.mongodb_client import save_case as mongo_save
        _case_id = st.session_state.get("case_id", "UNKNOWN")
        _email = (
            st.session_state.get("user_email")
            or state.get("user_email")
            or state.get("email")
            or "unknown"
        )
        _scenario = st.session_state.get("selected_scenario", "stellenwechsel")
        _status = state.get("status", "EN_COURS")
        mongo_save(_case_id, _email, _scenario, _status, state)
    except Exception:
        pass


def _new_case(user_name: str, user_email: str = "") -> dict:
    return {
        "case_id":               uuid.uuid4().hex[:8].upper(),
        "user_name":             user_name,
        "user_email":            user_email,
        "situation":             "",
        "structured_context":    {},
        "activated_actors":      [],         # list of Actor.value strings
        "requests":              {},         # actor.value → {sent_at, payload}
        "institution_responses": {},         # actor.value → response dict
        "institution_responded": {},         # actor.value → bool
        "actor_states":          {},         # actor.value → ActorState.value
        "orchestrator_state":    "INIT",
        "final_decision":        None,
        "created_at":            time.strftime("%Y-%m-%dT%H:%M:%S"),
        "follow_up_requests":    {},         # actor.value → {text, sent_at}
        "follow_up_questions":   {},         # actor.value → [{question, sent_at}]
        # Multi-turn async conversation (Phase 2)
        "institution_clarification_requests": {},  # actor.value → [{text, sent_at}]
        "user_clarification_responses":       {},  # actor.value → [{text, sent_at}]
    }


# ══════════════════════════════════════════════════════════════════════════════
# SESSION STATE — runtime store (orchestrator, navigation, UI flags)
# ══════════════════════════════════════════════════════════════════════════════

def _init_session() -> None:
    defaults: dict = {
        # Onboarding
        "onboarding_done":  False,
        "onboarding_step":  0,
        # Auth
        "logged_in":        False,
        "role":             None,        # "versicherter" | "institution"
        "user_name":        "",
        "user_email":       "",
        # Versicherter navigation
        "vs_step":          1,           # 1–7
        # Versicherter orchestration
        "orchestrator":     None,
        "raw_input":        "",
        "structured_ctx":   None,
        "activated_actors": None,        # set[Actor]
        "requests_sent":    False,
        "coord_start":      None,        # float — time.time() when requests sent
        "responses_done":   set(),       # set[Actor] already fed to orchestrator
        "llm_summary":      None,
        # Institution navigation
        "inst_view":        "dashboard", # "dashboard" | "form" | "done"
        "inst_actor":       None,        # Actor
        # Shared
        "case":             {},
        # Login transient
        "_login_role":      "versicherter",
        # Chat (H3 — Perceived Support)
        "chat_history":     [],          # list of {question, answer}
        # Demo mode toggle
        "auto_sim_enabled": False,       # False → institutions must respond manually (Live-Modus default)
        # Document extraction (Feature 2)
        "extracted_doc_data":  {},       # fields extracted from uploaded documents
        "_doc_upload_names":   [],       # track uploaded file names to detect new uploads
        # Scenario selection landing page
        "selected_scenario":   None,     # None | "stellenwechsel" (future: more scenarios)
        # Sparring Buddy (Step 1 chat interface)
        "sparring_messages":   [],
        "sparring_complete":   False,
        "sparring_situation":  "",
        "sparring_collected":  {},
        # MongoDB case tracking
        "case_id":             None,
        # HelveVista 2.0 additions
        "selected_option":        None,    # "A" | "B" | "C" | "D"
        "profile_complete":       False,
        "profile_data":           {},
        "chat_open":              False,
        "chat_messages_global":   [],
        "option_statuses":        {},      # {scenario: {option: status_str}}
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


_init_session()


# ══════════════════════════════════════════════════════════════════════════════
# UTILITY HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _use_llm() -> bool:
    """True when ANTHROPIC_API_KEY is set in the environment."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _vs_go(step: int) -> None:
    st.session_state.vs_step = step


def _logout() -> None:
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    _init_session()


def _actor_from_str(s: str) -> Optional[Actor]:
    for a in Actor:
        if a.value == s:
            return a
    return None


def _badge(label: str, kind: str) -> str:
    return f'<span class="hv-badge hv-badge-{kind}">{label}</span>'


def _fmt_chf(v: object) -> str:
    if v is None or str(v) in ("None", "null", ""):
        return "nicht angegeben"
    try:
        n = int(float(str(v)))
        return f"CHF {n:,}".replace(",", "'")
    except (ValueError, TypeError):
        return str(v)


def _fmt_str(v: object) -> str:
    """Return 'nicht angegeben' if value is None/'None'/'null', else str(v)."""
    if v is None or str(v) in ("None", "null", ""):
        return "nicht angegeben"
    return str(v)


def _fmt_date(d: object) -> str:
    """Format ISO date (YYYY-MM-DD) or German date string for display."""
    if d is None or str(d) in ("None", "null", ""):
        return "nicht angegeben"
    s = str(d)
    try:
        from datetime import datetime as _dt
        dt = _dt.strptime(s, "%Y-%m-%d")
        months = [
            "Januar", "Februar", "März", "April", "Mai", "Juni",
            "Juli", "August", "September", "Oktober", "November", "Dezember",
        ]
        return f"{dt.day}. {months[dt.month - 1]} {dt.year}"
    except (ValueError, TypeError):
        return s  # Already in German format or unrecognised — return as-is


def _fmt_status(s: object) -> str:
    """Translate internal status keys to German display strings."""
    mapping = {
        "austritt_bestaetigt": "Austritt bestätigt",
        "austritt_confirmed":  "Austritt bestätigt",
        "confirmed":           "Bestätigt",
        "pending":             "Ausstehend",
        "Austritt bestätigt":  "Austritt bestätigt",
    }
    if s is None or str(s) in ("None", "null", ""):
        return "nicht angegeben"
    return mapping.get(str(s), str(s))


# ══════════════════════════════════════════════════════════════════════════════
# LOGO + SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════

def _logo_large() -> None:
    if LOGO_FILE.exists():
        col_l, col_c, col_r = st.columns([1, 2, 1])
        with col_c:
            st.image(str(LOGO_FILE), width=280)
        st.markdown(
            '<div style="text-align:center; color:#C9A84C; font-size:0.6rem; '
            'letter-spacing:0.4em; margin-top:0.5rem; margin-bottom:1.5rem;">'
            "KLARHEIT · KONTROLLE · VORSORGE</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            """
            <div class="hv-logo-lg">
              <span class="helve">HELVE</span><span class="vista">VISTA</span>
              <span class="sub">KLARHEIT · KONTROLLE · VORSORGE</span>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _render_sidebar() -> None:
    with st.sidebar:
        if LOGO_FILE.exists():
            st.image(str(LOGO_FILE), width=140)
        else:
            st.markdown(
                """
                <div class="hv-logo-sm">
                  <span class="helve">HELVE</span><span class="vista">VISTA</span>
                  <span class="sub">KLARHEIT · KONTROLLE · VORSORGE</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

        role       = st.session_state.role
        user_name  = st.session_state.user_name
        case       = st.session_state.case
        case_id    = case.get("case_id", "—")
        role_label = "Versicherter" if role == "versicherter" else "Institution"
        role_color = "#C9A84C" if role == "versicherter" else "#5A9ABE"

        st.markdown(
            f'<div style="text-align:center; margin-bottom:0.8rem;">'
            f'<div style="color:{role_color}; font-size:0.62rem; letter-spacing:0.25em;">{role_label.upper()}</div>'
            f'<div style="color:#D0DCE8; font-size:0.95rem; margin-top:0.2rem;">{user_name}</div>'
            f"</div>",
            unsafe_allow_html=True,
        )

        if case_id != "—":
            st.markdown(
                f'<div style="text-align:center; margin-bottom:1rem;">'
                f'<div style="color:#2E4A5E; font-size:0.58rem; letter-spacing:0.2em; margin-bottom:0.2rem;">FALL-ID</div>'
                f'<div class="hv-case-id">{case_id}</div>'
                f"</div>",
                unsafe_allow_html=True,
            )

        st.markdown("---")

        if st.button(
            "Rolle wechseln",
            use_container_width=True,
            help="Für Demo-Zwecke zwischen Versicherter und Institution wechseln",
        ):
            new_role = "institution" if role == "versicherter" else "versicherter"
            st.session_state.role      = new_role
            st.session_state.vs_step   = 1
            st.session_state.inst_view = "dashboard"
            st.rerun()

        st.markdown("")

        if st.button("Abmelden", use_container_width=True):
            _logout()
            st.rerun()

        # ── Neuen Fall starten (both roles) ───────────────────────────────────
        if case_id != "—" or CASE_FILE.exists():
            st.markdown("")
            if st.button(
                "Neuen Fall starten",
                use_container_width=True,
                help="Fall und alle Daten zurücksetzen — startet einen neuen Demo-Durchlauf",
            ):
                if CASE_FILE.exists():
                    CASE_FILE.unlink()
                for key in list(st.session_state.keys()):
                    del st.session_state[key]
                _init_session()
                st.rerun()

        # ── Demo-Einstellungen (Versicherter only) ────────────────────────────
        if role == "versicherter":
            st.markdown("---")
            st.markdown(
                '<div class="hv-label" style="margin-bottom:0.4rem;">Demo-Einstellungen</div>',
                unsafe_allow_html=True,
            )
            auto_sim = st.toggle(
                "Simulationsmodus",
                value=st.session_state.get("auto_sim_enabled", False),
                key="auto_sim_toggle",
                help=(
                    "Ein: Institutionen antworten automatisch nach "
                    f"{AUTO_SIM_DELAY:.0f} Sekunden (Demo-Modus). "
                    "Aus: Institutionen antworten manuell über das Institutionen-Portal (Live-Modus)."
                ),
            )
            st.session_state.auto_sim_enabled = auto_sim
            if auto_sim:
                st.caption("Demo-Modus")
            else:
                st.caption("Live-Modus")

        # ── Live orchestrator status (Versicherter only, when active) ─────────
        orch: Optional[HelveVistaOrchestrator] = st.session_state.orchestrator
        if role == "versicherter" and orch is not None:
            st.markdown("---")
            st.markdown(
                '<div class="hv-label" style="margin-bottom:0.4rem;">Prozess-Status</div>',
                unsafe_allow_html=True,
            )
            st.caption(f"Orchestrator: `{orch.state.value}`")
            for actor, process in orch.actors.items():
                icon = STATE_DISPLAY.get(process.state, ("—", "", ""))[0]
                st.caption(f"{icon} {ACTOR_LABELS[actor]}: `{process.state.value}`")


# ══════════════════════════════════════════════════════════════════════════════
# STEP PROGRESS BAR (Versicherter)
# ══════════════════════════════════════════════════════════════════════════════

def _render_steps(current: int) -> None:
    parts: list[str] = []
    for i, name in enumerate(STEP_NAMES, 1):
        cls = "done" if i < current else ("active" if i == current else "")
        parts.append(f'<div class="hv-step {cls}">{name}</div>')
    st.markdown(
        f'<div class="hv-steps">{"".join(parts)}</div>',
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# INSTITUTION RESPONSE SIMULATION
#
# Institutional responses simulated via LLM for prototype evaluation purposes.
# To be replaced by real institutional actors in production.
# See Kap. 8 of Bachelor Thesis for academic justification.
# ══════════════════════════════════════════════════════════════════════════════

def _simulate_llm(actor: Actor, context: dict) -> dict:
    """
    Institutional responses simulated via LLM for prototype evaluation purposes.
    To be replaced by real institutional actors in production.
    See Kap. 8 of Bachelor Thesis for academic justification.

    Calls the Claude API to generate a realistic institutional response.
    The LLM acts as the institution and returns structured JSON using ONLY
    data present in the case — no hallucinated values.
    """
    import anthropic

    client = anthropic.Anthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY")
    )

    actor_name = ACTOR_LABELS[actor]

    # Load full case data — situation text + vorsorge_ausweis are sources of truth
    case           = _load_case()
    situation      = case.get("situation", context.get("user_summary", ""))
    user_name      = case.get("user_name", "")
    vorsorge       = case.get("vorsorge_ausweis", {})
    structured_ctx = case.get("structured_context", {})

    # Resolved field values (prefer vorsorge_ausweis, fall back to structured_context)
    freizueg_val = (
        vorsorge.get("freizuegigkeit_chf")
        or vorsorge.get("gesamtguthaben_chf")
        or vorsorge.get("altersguthaben_chf")
    )
    koord_val = (
        vorsorge.get("koordinationsabzug_chf")
        or vorsorge.get("bvg_koordinationsabzug")
    )


    data_summary = (
        f"SITUATION DES VERSICHERTEN:\n{situation}\n\n"
        f"DATEN AUS DEM VORSORGEAUSWEIS:\n"
        f"- Freizügigkeitsguthaben: {freizueg_val if freizueg_val is not None else 'nicht im Dokument'}\n"
        f"- BVG-Koordinationsabzug: {koord_val if koord_val is not None else 'nicht im Dokument'}\n"
        f"- Austrittsdatum: {vorsorge.get('austrittsdatum') or 'aus Situationstext extrahieren'}\n"
        f"- Eintrittsdatum: {vorsorge.get('eintrittsdatum') or 'aus Situationstext extrahieren'}\n"
        f"- AHV-Nummer: {vorsorge.get('ahv_nummer') or 'nicht angegeben'}\n"
        f"- Alter Arbeitgeber: {vorsorge.get('arbeitgeber') or structured_ctx.get('old_employer') or 'aus Situationstext'}\n"
        f"- Neuer Arbeitgeber: {vorsorge.get('neuer_arbeitgeber') or structured_ctx.get('new_employer') or 'aus Situationstext'}\n"
    )

    anti_hallucination = (
        "Antworte NUR auf Basis der bereitgestellten Daten. "
        "Wenn eine Information nicht vorhanden ist, antworte mit null. "
        "Erfinde keine Werte. Keine generischen Antworten."
    )

    if actor == Actor.OLD_PK:
        system_prompt = (
            "Du bist die alte Pensionskasse. Lies die Situationsdaten sorgfältig.\n"
            f"{data_summary}\n"
            "Extrahiere Austrittsdatum aus dem Situationstext wenn nicht im Vorsorgeausweis.\n"
            f"Der exakte Wert für freizuegigkeit_chf laut Vorsorgeausweis ist: {freizueg_val}\n"
            f"Gib diesen Wert EXAKT als Integer zurück. Kein null, kein anderer Wert.\n"
            f"{anti_hallucination}\n"
            "Antworte NUR mit JSON: "
            "{\"freizuegigkeit_chf\": <Wert oder null>, "
            "\"austrittsdatum\": \"YYYY-MM-DD\", "
            "\"status\": \"austritt_bestaetigt\"}"
        )
    elif actor == Actor.NEW_PK:
        system_prompt = (
            "Du bist die neue Pensionskasse. Lies die Situationsdaten sorgfältig.\n"
            f"{data_summary}\n"
            "Extrahiere Eintrittsdatum aus dem Situationstext wenn nicht im Vorsorgeausweis.\n"
            f"Der exakte Wert für bvg_koordinationsabzug laut Vorsorgeausweis ist: {koord_val}\n"
            f"Gib diesen Wert EXAKT als Integer zurück. Kein null, kein anderer Wert.\n"
            f"{anti_hallucination}\n"
            "Antworte NUR mit exakt diesem JSON-Format (bvg_pflicht muss true sein): "
            "{\"eintrittsdatum\": \"YYYY-MM-DD\", "
            "\"bvg_koordinationsabzug\": <Wert oder null>, \"bvg_pflicht\": true}"
        )
    else:  # AVS
        system_prompt = (
            "Du bist die AHV-Ausgleichskasse. Lies die Situationsdaten sorgfältig.\n"
            f"{data_summary}\n"
            "\nExtrahiere aus dem Situationstext:\n"
            "- Geburtsdatum des Versicherten (falls vorhanden)\n"
            "- AHV-Nummer (falls im Vorsorgeausweis vorhanden)\n"
            "\nBerechne die Beitragsjahre basierend auf dem Eintrittsdatum\n"
            "der ersten Anstellung (falls bekannt) bis heute (2026).\n"
            "\n"
            f"{anti_hallucination}\n"
            "Antworte NUR mit JSON: "
            "{\"ik_auszug_verfuegbar\": true, "
            "\"ahv_nummer\": \"<aus Vorsorgeausweis oder null>\", "
            "\"beitragsjahre\": <Zahl oder null>, "
            "\"luecken\": 0, "
            "\"status\": \"IK-Auszug bereitgestellt\"}"
        )

    user_msg = (
        f"Versicherter: {user_name}\n\n"
        f"Situationstext:\n{situation}"
    )

    try:
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=256,
            system=system_prompt,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = msg.content[0].text.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(raw)
        # Unwrap if LLM still returned {actor_key: {...}} instead of flat dict
        if actor.value in parsed and isinstance(parsed.get(actor.value), dict):
            parsed = parsed[actor.value]
        # Guarantee bvg_pflicht is always True for NEW_PK
        if actor == Actor.NEW_PK:
            parsed["bvg_pflicht"] = True
        return parsed
    except Exception:
        return DEMO_RESPONSES[actor]


def _simulate_response(actor: Actor, context: dict) -> dict:
    """
    Institutional responses simulated via LLM for prototype evaluation purposes.
    To be replaced by real institutional actors in production.
    See Kap. 8 of Bachelor Thesis for academic justification.
    """
    if _use_llm():
        return _simulate_llm(actor, context)
    return DEMO_RESPONSES[actor]


# ══════════════════════════════════════════════════════════════════════════════
# LOGIN PAGE
# ══════════════════════════════════════════════════════════════════════════════

def _page_login() -> None:
    _logo_large()

    st.markdown(
        '<div class="hv-label" style="text-align:center; margin-bottom:1.2rem;">Bitte wählen Sie Ihre Rolle</div>',
        unsafe_allow_html=True,
    )

    # Role selector — two styled columns acting as cards
    col_v, col_i = st.columns(2, gap="medium")
    current_role = st.session_state.get("_login_role", "versicherter")

    with col_v:
        is_v  = current_role == "versicherter"
        style = "primary" if is_v else "secondary"
        if st.button(
            "Versicherter\n\nPrivatperson",
            key="_btn_role_v",
            use_container_width=True,
            type=style,
        ):
            st.session_state["_login_role"] = "versicherter"
            st.rerun()
        if is_v:
            st.markdown(
                '<div style="text-align:center; color:#C9A84C; font-size:0.68rem; margin-top:0.2rem; letter-spacing:0.1em;">AUSGEWÄHLT</div>',
                unsafe_allow_html=True,
            )

    with col_i:
        is_i  = current_role == "institution"
        style = "primary" if is_i else "secondary"
        if st.button(
            "Institution\n\nPensionskasse / Arbeitgeber",
            key="_btn_role_i",
            use_container_width=True,
            type=style,
        ):
            st.session_state["_login_role"] = "institution"
            st.rerun()
        if is_i:
            st.markdown(
                '<div style="text-align:center; color:#C9A84C; font-size:0.68rem; margin-top:0.2rem; letter-spacing:0.1em;">AUSGEWÄHLT</div>',
                unsafe_allow_html=True,
            )

    st.markdown("<div style='height:1.2rem'></div>", unsafe_allow_html=True)

    name = st.text_input(
        "Name",
        placeholder="Vor- und Nachname",
        key="_login_name_input",
        label_visibility="visible",
    )

    email = st.text_input(
        "E-Mail-Adresse",
        placeholder="vorname.nachname@beispiel.ch",
        key="_login_email_input",
        label_visibility="visible",
    )

    st.markdown("<div style='height:0.6rem'></div>", unsafe_allow_html=True)

    if st.button("Anmelden", type="primary", use_container_width=True):
        if not name.strip():
            st.warning("Bitte geben Sie Ihren Namen ein.")
        elif not email.strip() or "@" not in email:
            st.warning("Bitte geben Sie eine gültige E-Mail-Adresse ein.")
        else:
            chosen = st.session_state.get("_login_role", "versicherter")
            st.session_state.logged_in  = True
            st.session_state.role       = chosen
            st.session_state.user_name  = name.strip()
            st.session_state.user_email = email.strip()

            existing = _load_case()
            if existing:
                st.session_state.case = existing
            else:
                fresh = _new_case(name.strip(), email.strip())
                st.session_state.case = fresh
                _save_case(fresh)

            st.rerun()

    st.markdown(
        '<div class="hv-footer">Sicher verschlüsselt · FINMA-konform · Schweizer Hosting</div>',
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# SPARRING BUDDY — Step 1 chat interface
# ══════════════════════════════════════════════════════════════════════════════

MANDATORY_FIELDS = [
    "name",
    "alter_arbeitgeber",
    "alter_arbeitgeber_ort",
    "neuer_arbeitgeber",
    "neuer_arbeitgeber_ort",
    "austrittsdatum",
    "eintrittsdatum",
    "email_alte_pk",
    "email_neue_pk",
    "situation_beschreibung",
]

MANDATORY_FIELDS_AVS = [
    "name",
    "geburtsdatum",
    "ahv_nummer",
    "grund_der_anfrage",
    "situation_beschreibung",
]

VORSORGE_TO_SPARRING = {
    # Identity
    "name":                   "name",
    "geburtsdatum":           "geburtsdatum",
    "ahv_nummer":             "ahv_nummer",
    # Old employer / old PK
    "arbeitgeber":            "alter_arbeitgeber",
    "arbeitgeber_ort":        "alter_arbeitgeber_ort",
    "austrittsdatum":         "austrittsdatum",
    "email":                  "email_alte_pk",
    # Financial data
    "freizuegigkeit_chf":     "freizuegigkeit_chf",
    "koordinationsabzug_chf": "koordinationsabzug_chf",
    # New employer (if present in Vorsorgeausweis)
    "neuer_arbeitgeber":      "neuer_arbeitgeber",
    "eintrittsdatum":         "eintrittsdatum",
}

FIELD_LABELS_DE = {
    "name":                   "Name",
    "alter_arbeitgeber":      "Alter Arbeitgeber",
    "alter_arbeitgeber_ort":  "Ort (alter AG)",
    "neuer_arbeitgeber":      "Neuer Arbeitgeber",
    "neuer_arbeitgeber_ort":  "Ort (neuer AG)",
    "austrittsdatum":         "Austrittsdatum",
    "eintrittsdatum":         "Eintrittsdatum",
    "email_alte_pk":          "E-Mail Alte PK",
    "email_neue_pk":          "E-Mail Neue PK",
    "ahv_nummer":             "AHV-Nummer",
    "freizuegigkeit_chf":     "Freizügigkeitsguthaben",
    "koordinationsabzug_chf": "Koordinationsabzug",
    "geburtsdatum":           "Geburtsdatum",
    "grund_der_anfrage":      "Grund der AHV-Anfrage",
    "situation_beschreibung": "Beschreibung der Situation",
}


def _sparring_extract_info(messages: list) -> dict:
    """
    Call Claude API with conversation history and extract structured fields.
    Returns a dict of non-null field values found in the conversation.
    On any exception returns {}.
    """
    import anthropic
    try:
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        system = (
            "Analysiere dieses Gespräch und extrahiere alle genannten Informationen. "
            "Antworte NUR mit JSON, kein Text davor oder danach:\n"
            "{\n"
            '  "name": null,\n'
            '  "geburtsdatum": null,\n'
            '  "ahv_nummer": null,\n'
            '  "alter_arbeitgeber": null,\n'
            '  "alter_arbeitgeber_ort": null,\n'
            '  "neuer_arbeitgeber": null,\n'
            '  "neuer_arbeitgeber_ort": null,\n'
            '  "austrittsdatum": null,\n'
            '  "eintrittsdatum": null,\n'
            '  "email_alte_pk": null,\n'
            '  "email_neue_pk": null,\n'
            '  "freizuegigkeit_chf": null,\n'
            '  "koordinationsabzug_chf": null,\n'
            '  "versicherter_lohn": null,\n'
            '  "situation_beschreibung": null\n'
            "}\n"
            "Setze null wenn nicht erwähnt. Nur JSON."
        )
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=512,
            system=system,
            messages=messages,
        )
        raw = msg.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        parsed = json.loads(raw)
        return {k: v for k, v in parsed.items() if v is not None}
    except Exception:
        return {}


def _sparring_generate_situation() -> str:
    """
    Merge sparring_collected with vorsorge data, then call Claude to produce
    a 3–5 sentence German prose description of the user's situation.
    Stores result in st.session_state.sparring_situation and returns it.
    On any exception returns "".
    """
    import anthropic
    try:
        vorsorge = _load_case().get("vorsorge_ausweis", {})
        merged: dict = {}
        merged.update({k: v for k, v in vorsorge.items() if v is not None})
        merged.update(st.session_state.sparring_collected)

        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        prompt = (
            "Schreibe einen deutschen Fliesstext (3-5 Sätze) in der Ich-Form "
            "des Versicherten, der die Situation für HelveVista beschreibt. "
            "Enthalte: Name, Stellenwechsel-Details, Arbeitgeber, Daten, "
            "Vorsorgewunsch. Professionell und vollständig.\n"
            f"Daten: {json.dumps(merged, ensure_ascii=False)}"
        )
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        st.session_state.sparring_situation = text
        return text
    except Exception:
        return ""


def _sparring_llm_response() -> None:
    """
    Generate the next assistant message in the Sparring Buddy conversation.
    Checks which MANDATORY_FIELDS are still missing from sparring_collected,
    calls Claude with a structured system prompt, appends the response, and
    updates sparring_collected by re-extracting from the full conversation.
    Sets sparring_complete=True when all mandatory fields are present.
    """
    import anthropic
    try:
        collected = st.session_state.sparring_collected

        # Build missing list — scenario-aware, exclude pre-filled fields
        scenario = st.session_state.get(
            "selected_scenario", "stellenwechsel"
        )
        active_fields = (
            MANDATORY_FIELDS_AVS
            if scenario == "revue_avs"
            else MANDATORY_FIELDS
        )
        missing_list = [
            FIELD_LABELS_DE.get(f, f)
            for f in active_fields
            if not collected.get(f)
        ]

        if not missing_list:
            st.session_state.sparring_complete = True
            return

        pre_filled_summary = "\n".join(
            f"  ✓ {FIELD_LABELS_DE.get(k, k)}: {v}"
            for k, v in collected.items()
            if v
        ) or "  (keine vorausgefüllten Daten)"

        system = (
            "Du bist HelveVista, ein professioneller Schweizer Vorsorge-Assistent.\n"
            "Führe ein strukturiertes, pädagogisches Gespräch auf Deutsch.\n\n"
            f"BEREITS BESTÄTIGT — diese Felder NICHT nochmals fragen:\n{pre_filled_summary}\n\n"
            f"NOCH FEHLENDE PFLICHTANGABEN:\n{', '.join(missing_list)}\n\n"
            "WICHTIG: Der Nutzer muss IMMER seine Situation in "
            "eigenen Worten beschreiben (Feld: Beschreibung der "
            "Situation). Frage danach ZULETZT, nachdem alle anderen "
            "Pflichtfelder gesammelt wurden. Ohne diese Beschreibung "
            "ist der Fall NICHT vollständig.\n\n"
            "KOMMUNIKATIONSSTIL:\n"
            "- Stelle zusammengehörige Fragen ZUSAMMEN in einer einzigen Nachricht\n"
            "- Erkläre IMMER kurz WARUM du diese Information benötigst\n"
            "  Beispiel: 'Damit HelveVista Ihre alte Pensionskasse direkt "
            "kontaktieren kann, benötigen wir deren E-Mail-Adresse.'\n"
            "- Gruppiere logisch zusammengehörige Fragen:\n"
            "  Gruppe 1: Name + Geburtsdatum (Identifikation)\n"
            "  Gruppe 2: Alter Arbeitgeber + Ort + Austrittsdatum "
            "(bisherige Anstellung)\n"
            "  Gruppe 3: Neuer Arbeitgeber + Ort + Eintrittsdatum "
            "(neue Anstellung)\n"
            "  Gruppe 4: E-Mail alte PK + E-Mail neue PK "
            "(für direkte Kontaktaufnahme)\n"
            "- Maximal 1 Gruppe pro Nachricht\n"
            "- Bestätige erhaltene Informationen kurz und freundlich\n"
            "- Frage NUR nach fehlenden Pflichtangaben\n"
            "- Wenn ALLE Pflichtangaben vollständig: schreibe exakt auf "
            "neuer Zeile: [SPARRING_COMPLETE]\n"
            "- Ausschliesslich Deutsch\n"
            "- Ton: professionell aber warm — wie ein erfahrener Berater"
        )

        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=512,
            system=system,
            messages=st.session_state.sparring_messages,
        )
        raw_response = msg.content[0].text.strip()

        complete = "[SPARRING_COMPLETE]" in raw_response
        clean_response = raw_response.replace("[SPARRING_COMPLETE]", "").strip()

        if complete:
            st.session_state.sparring_complete = True

        st.session_state.sparring_messages.append(
            {"role": "assistant", "content": clean_response}
        )

        # Re-extract structured info from full conversation
        extracted = _sparring_extract_info(st.session_state.sparring_messages)
        for k, v in extracted.items():
            if v is not None:
                st.session_state.sparring_collected[k] = v

        # Re-check if now complete after extraction
        still_missing = [f for f in active_fields if not st.session_state.sparring_collected.get(f)]
        if not still_missing:
            st.session_state.sparring_complete = True

    except Exception as exc:
        st.session_state.sparring_messages.append({
            "role": "assistant",
            "content": f"Entschuldigung, es ist ein Fehler aufgetreten. Bitte versuchen Sie es erneut. ({exc})",
        })


def _sparring_buddy_chat() -> None:
    """
    Render the Sparring Buddy chat interface for Step 1.
    Pre-fills sparring_collected from vorsorge_ausweis on first call.
    The conversation collects all MANDATORY_FIELDS, then generates a
    situation text and advances to Step 2.
    """
    # A) LOAD DATA
    case = _load_case() or st.session_state.case
    vorsorge = case.get("vorsorge_ausweis", {})

    # B) PRE-FILL FROM VORSORGE — runs every render,
    #    only injects keys not yet in sparring_collected
    needs_update = False
    if vorsorge:
        for v_key, s_key in VORSORGE_TO_SPARRING.items():
            val = vorsorge.get(v_key)
            if val and not st.session_state.sparring_collected.get(s_key):
                st.session_state.sparring_collected[s_key] = val
                needs_update = True

    collected = st.session_state.sparring_collected
    confirmed_list = [
        FIELD_LABELS_DE.get(k, k)
        for k in FIELD_LABELS_DE
        if collected.get(k)
    ]
    still_missing = [
        FIELD_LABELS_DE.get(f, f)
        for f in MANDATORY_FIELDS
        if not collected.get(f)
    ]

    confirmed_str = "".join(
        f"✓ {item}<br>" for item in confirmed_list
    )
    missing_str = (
        "".join(f"→ {item}<br>" for item in still_missing)
        if still_missing
        else "Keine weiteren Angaben erforderlich."
    )

    # Opening message — only if no messages yet
    if not st.session_state.sparring_messages:
        if confirmed_list:
            opening = (
                "Guten Tag! Ich habe Ihren Vorsorgeausweis gelesen "
                "und folgende Angaben bereits erfasst:<br><br>"
                f"<span style='color:#6fcf97;font-size:0.85rem;'>{confirmed_str}</span>"
                "<br>Noch benötigt:<br>"
                f"<span style='color:#C9A84C;font-size:0.85rem;'>{missing_str}</span>"
                "<br>Dürfen wir beginnen?"
            )
        else:
            opening = (
                "Guten Tag! Ich bin HelveVista, Ihr persönlicher "
                "Vorsorge-Assistent. Sie können optional Ihren "
                "Vorsorgeausweis hochladen — ich lese ihn automatisch "
                "und spare Ihnen viele Fragen. "
                "Wie heissen Sie vollständig?"
            )
        st.session_state.sparring_messages.append(
            {"role": "assistant", "content": opening}
        )
    elif needs_update and len(st.session_state.sparring_messages) == 1:
        # PDF uploaded after opening message — refresh it
        updated_opening = (
            "Ich habe Ihren Vorsorgeausweis soeben gelesen "
            "und folgende Angaben erfasst:<br><br>"
            f"<span style='color:#6fcf97;font-size:0.85rem;'>{confirmed_str}</span>"
            "<br>Noch benötigt:<br>"
            f"<span style='color:#C9A84C;font-size:0.85rem;'>{missing_str}</span>"
            "<br>Dürfen wir beginnen?"
        )
        st.session_state.sparring_messages[0] = {
            "role": "assistant",
            "content": updated_opening,
        }

    # C) DISPLAY CHAT MESSAGES
    # ── Chat container header ─────────────────────────
    collected = st.session_state.sparring_collected
    scenario = st.session_state.get("selected_scenario", "stellenwechsel")
    active_fields = (
        MANDATORY_FIELDS_AVS
        if scenario == "revue_avs"
        else MANDATORY_FIELDS
    )
    total_mandatory = len(active_fields)
    collected_count = len([
        f for f in active_fields if collected.get(f)
    ])
    progress_pct = min(int(collected_count / total_mandatory * 100), 100)

    st.markdown(
        f"""
<div style="background:#0a1929; border:1.5px solid #1a3a5c;
            border-radius:12px; padding:0; margin-bottom:8px;
            overflow:hidden;">

  <!-- Chat header bar -->
  <div style="background:#0d2137; padding:12px 20px;
              border-bottom:1px solid #1a3a5c;
              display:flex; align-items:center; gap:12px;">
    <div style="width:36px; height:36px; border-radius:50%;
                background:#C9A84C; display:flex;
                align-items:center; justify-content:center;
                font-weight:700; font-size:0.85rem;
                color:#0d1f2d; flex-shrink:0;">HV</div>
    <div>
      <div style="color:#FFFFFF; font-weight:600;
                  font-size:0.95rem;">HelveVista</div>
      <div style="color:#7A96B0; font-size:0.75rem;">
        Persönlicher Vorsorge-Assistent</div>
    </div>
    <div style="margin-left:auto; text-align:right;">
      <div style="color:#C9A84C; font-size:0.75rem;
                  font-weight:600;">{collected_count}/{total_mandatory} Angaben</div>
      <div style="background:#1a3a5c; border-radius:4px;
                  height:4px; width:80px; margin-top:4px;">
        <div style="background:#C9A84C; height:4px;
                    border-radius:4px;
                    width:{progress_pct}%;"></div>
      </div>
    </div>
  </div>

  <!-- Messages area -->
  <div style="padding:16px 20px; max-height:420px;
              overflow-y:auto; display:flex;
              flex-direction:column; gap:12px;">
""",
        unsafe_allow_html=True,
    )

    for msg in st.session_state.sparring_messages:
        if msg["role"] == "assistant":
            st.markdown(
                f"""
<div style="display:flex; align-items:flex-start; gap:10px;">
  <div style="width:28px; height:28px; border-radius:50%;
              background:#C9A84C; display:flex;
              align-items:center; justify-content:center;
              font-weight:700; font-size:0.7rem;
              color:#0d1f2d; flex-shrink:0; margin-top:2px;">HV</div>
  <div style="background:#0d2137; border:1px solid #1e3d5c;
              border-radius:4px 12px 12px 12px;
              padding:16px 20px; max-width:88%;
              color:#e0e8f0; font-size:1.0rem;
              line-height:1.75;">
    {msg["content"]}
  </div>
</div>
""",
                unsafe_allow_html=True,
            )
        elif msg["role"] == "user":
            st.markdown(
                f"""
<div style="display:flex; justify-content:flex-end;">
  <div style="background:#1a2d1a; border:1px solid #C9A84C;
              border-radius:12px 4px 12px 12px;
              padding:12px 16px; max-width:80%;
              color:#ffffff; font-size:0.9rem;
              line-height:1.6;">
    {msg["content"]}
  </div>
</div>
""",
                unsafe_allow_html=True,
            )

    st.markdown("</div></div>", unsafe_allow_html=True)

    # D) INPUT (only if not complete)
    if not st.session_state.sparring_complete:
        st.markdown(
            """
<div style="margin-top:16px; margin-bottom:8px;
            background:#0a1929; border:1.5px solid #C9A84C;
            border-radius:10px; padding:16px 20px;">
  <div style="color:#C9A84C; font-size:0.72rem;
              letter-spacing:0.15em; font-weight:600;
              margin-bottom:10px;">
    IHRE ANTWORT
  </div>
</div>
""",
            unsafe_allow_html=True,
        )
        col_in, col_btn = st.columns([5, 1])
        with col_in:
            user_input = st.text_input(
                "Ihre Antwort",
                placeholder="Schreiben Sie hier Ihre Antwort…",
                key="sparring_input",
                label_visibility="collapsed",
            )
        with col_btn:
            send = st.button(
                "Senden",
                key="sparring_send",
                type="primary",
                use_container_width=True,
            )
        if send and user_input.strip():
            st.session_state.sparring_messages.append(
                {"role": "user", "content": user_input.strip()}
            )
            with st.spinner("HelveVista schreibt…"):
                _sparring_llm_response()
            st.rerun()

    # E) COMPLETION
    if st.session_state.sparring_complete:
        st.success("Alle notwendigen Angaben wurden erfasst.")
        st.markdown("---")

        collected = st.session_state.sparring_collected
        st.markdown('<div class="hv-label">Zusammenfassung der erfassten Angaben</div>', unsafe_allow_html=True)
        for key, label in FIELD_LABELS_DE.items():
            val = collected.get(key)
            if val:
                col_l, col_r = st.columns([2, 3])
                with col_l:
                    st.caption(label)
                with col_r:
                    st.markdown(f"**{val}**")

        st.markdown("---")
        if st.button("Weiter", key="sparring_weiter", type="primary", use_container_width=False):
            situation_text = _sparring_generate_situation()
            existing = _load_case() or {}
            case = st.session_state.case
            case["situation"] = situation_text
            if not case.get("vorsorge_ausweis") and existing.get("vorsorge_ausweis"):
                case["vorsorge_ausweis"] = existing["vorsorge_ausweis"]
            st.session_state.case = case
            st.session_state.raw_input = situation_text
            _save_case(case)
            _vs_go(2)
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# VERSICHERTER FLOW — Steps 1–6 + Final
# ══════════════════════════════════════════════════════════════════════════════

def _vs_step_1_situation() -> None:
    """Step 1 — Situationsbeschreibung"""
    _render_steps(1)

    st.markdown('<div class="hv-label">Schritt 1 von 6</div>', unsafe_allow_html=True)
    st.markdown("## Ihre Situation")
    st.markdown(
        "Beschreiben Sie Ihre Situation auf Deutsch. HelveVista erkennt automatisch, "
        "welche Vorsorgeeinrichtungen kontaktiert werden müssen, und koordiniert "
        "den gesamten Prozess sicher und nachvollziehbar für Sie."
    )

    st.markdown("<div style='height:0.4rem'></div>", unsafe_allow_html=True)

    # ── Document upload (Feature 2) ────────────────────────────────────────────
    st.markdown("#### Dokumente hochladen (optional)")
    st.caption(
        "Laden Sie relevante Dokumente hoch. HelveVista extrahiert automatisch "
        "Vorsorge- und Kontaktinformationen."
    )

    uploaded_files = st.file_uploader(
        "Dokumente hochladen",
        accept_multiple_files=True,
        type=["pdf", "png", "jpg", "jpeg"],
        key="doc_upload",
        label_visibility="collapsed",
    )

    if uploaded_files:
        current_names = sorted(f.name for f in uploaded_files)
        prev_names    = sorted(st.session_state.get("_doc_upload_names", []))

        if current_names != prev_names:
            # New files detected — run extraction
            st.session_state["_doc_upload_names"] = current_names
            if _use_llm():
                with st.spinner("Dokument wird analysiert…"):
                    extracted = _extract_doc_info(list(uploaded_files))
                if extracted is not None:
                    st.session_state.extracted_doc_data = extracted
                    # Save extracted PDF data to case_state.json AND session state
                    # (must update both so the "Weiter" button does not overwrite)
                    _case = _load_case()
                    _case["vorsorge_ausweis"] = extracted
                    st.session_state.case["vorsorge_ausweis"] = extracted
                    _save_case(_case)
                    st.rerun()
            else:
                st.info("LLM-Extraktion erfordert einen ANTHROPIC_API_KEY.")

    extracted_data = st.session_state.get("extracted_doc_data", {})
    if extracted_data:
        st.success("Informationen aus Dokument extrahiert")
        _label_map_disp = {
            "name":               "Name",
            "ahv_nummer":         "AHV-Nummer",
            "pensionskasse":      "Pensionskasse",
            "freizuegigkeit_chf": "Freizügigkeitsguthaben (CHF)",
            "austrittsdatum":     "Austrittsdatum",
            "eintrittsdatum":     "Eintrittsdatum",
            "email":              "E-Mail Institution",
            "telefon":            "Telefon Institution",
        }
        for k, v in extracted_data.items():
            label = _label_map_disp.get(k, k.replace("_", " ").title())
            st.caption(f"**{label}:** {v}")

    _sparring_buddy_chat()


def _vs_step_2_analyse() -> None:
    """Step 2 — Fall strukturieren (LLM or demo mode)"""
    _render_steps(2)

    st.markdown('<div class="hv-label">Schritt 2 von 6</div>', unsafe_allow_html=True)
    st.markdown("## Analyse Ihrer Situation")

    raw = st.session_state.raw_input

    # Run LLM structuring exactly once, then cache in session_state
    if st.session_state.structured_ctx is None:
        if _use_llm():
            with st.spinner("HelveVista analysiert Ihre Eingabe…"):
                from llm.structurer import structure_user_input  # noqa: PLC0415
                ctx = structure_user_input(raw)
        else:
            ctx = {
                "use_case":        "STELLENWECHSEL",
                "actors_involved": ["OLD_PK", "NEW_PK"],
                "avs_required":    False,
                "user_summary":    raw,
                "missing_info":    [],
                "actors_enum":     [Actor.OLD_PK, Actor.NEW_PK],
            }
        st.session_state.structured_ctx = ctx

        # Persist structured context (without non-serialisable enum objects)
        existing = _load_case() or {}
        case = st.session_state.case
        case["structured_context"] = {
            k: v
            for k, v in ctx.items()
            if k != "actors_enum"
        }
        if not case.get("vorsorge_ausweis") and existing.get("vorsorge_ausweis"):
            case["vorsorge_ausweis"] = existing["vorsorge_ausweis"]
        _save_case(case)

    ctx = st.session_state.structured_ctx

    st.markdown('<div class="hv-label" style="margin-top:0.5rem;">Erkannte Situation</div>', unsafe_allow_html=True)
    with st.container(border=True):
        use_case = ctx.get("use_case", "STELLENWECHSEL").replace("_", " ").title()
        st.markdown(f"**Verfahren:** {use_case}")
        st.markdown(f"**Zusammenfassung:** {ctx.get('user_summary', raw[:240])}")
        missing = ctx.get("missing_info", [])
        if missing:
            st.markdown("**Fehlende Angaben:**")
            for m in missing:
                st.caption(f"  · {m}")

    if not _use_llm():
        st.info(
            "Demo-Modus: Standardfall Stellenwechsel erkannt "
            "(Alte Pensionskasse + Neue Pensionskasse)."
        )

    st.markdown("<div style='height:0.4rem'></div>", unsafe_allow_html=True)

    col_back, col_next = st.columns(2)
    with col_back:
        if st.button("Zurück", use_container_width=True):
            st.session_state.structured_ctx = None
            _vs_go(1)
            st.rerun()
    with col_next:
        if st.button("Weiter", type="primary", use_container_width=True):
            _vs_go(3)
            st.rerun()


def _vs_step_3_akteure() -> None:
    """Step 3 — Akteure aktivieren (card-style selection)"""
    _render_steps(3)

    st.markdown('<div class="hv-label">Schritt 3 von 6</div>', unsafe_allow_html=True)
    ctx       = st.session_state.structured_ctx
    suggested = set(ctx.get("actors_enum", [Actor.OLD_PK, Actor.NEW_PK]))
    scenario  = st.session_state.get("selected_scenario", "stellenwechsel")

    st.markdown("## Beteiligte Institutionen")
    if scenario == "revue_avs":
        st.markdown(
            "HelveVista koordiniert Ihre AHV-Anfrage direkt mit der "
            "zuständigen Ausgleichskasse."
        )
    else:
        st.markdown(
            "HelveVista hat folgende Institutionen für Ihren Fall identifiziert. "
            "Alte und neue Pensionskasse sind für den Stellenwechsel obligatorisch."
        )

    st.markdown("<div style='height:0.4rem'></div>", unsafe_allow_html=True)

    selected: dict[Actor, bool] = {}
    for actor in Actor:
        # For revue_avs: only show AVS, hide PK actors
        if scenario == "revue_avs" and actor != Actor.AVS:
            continue

        if scenario == "revue_avs":
            mandatory = True  # AVS is mandatory for revue_avs
            is_sug    = True
        else:
            mandatory = actor in {Actor.OLD_PK, Actor.NEW_PK}
            is_sug    = actor in suggested
        label     = ACTOR_LABELS[actor]
        desc      = ACTOR_DESCRIPTIONS[actor]

        with st.container(border=True):
            col_cb, col_info = st.columns([1, 11])
            with col_cb:
                checked = st.checkbox(
                    label,
                    value=is_sug,
                    key=f"act_{actor.value}",
                    disabled=mandatory,
                    label_visibility="collapsed",
                )
                selected[actor] = True if mandatory else checked
            with col_info:
                tags = ""
                if mandatory:
                    tags += ' <span style="color:#C9A84C; font-size:0.7rem;">· Obligatorisch</span>'
                elif is_sug:
                    tags += ' <span style="color:#5A9ABE; font-size:0.7rem;">· Empfohlen</span>'
                st.markdown(
                    f'<span style="font-weight:500;">{label}</span>{tags}',
                    unsafe_allow_html=True,
                )
                st.caption(desc)

    st.markdown("<div style='height:0.4rem'></div>", unsafe_allow_html=True)

    # ── Email addresses for live mode ──────────────────────────────────────────
    st.markdown(
        '<div class="hv-label" style="margin-top:0.6rem; margin-bottom:0.3rem;">'
        'E-Mail-Adressen (Live-Modus)</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Nur relevant wenn Simulationsmodus deaktiviert ist. "
        "HelveVista sendet dann echte Anfragen per E-Mail an die Institutionen."
    )
    DEFAULT_INSTITUTION_EMAILS = {
        "OLD_PK": "info.helvevista@gmail.com",
        "NEW_PK": "info.helvevista@gmail.com",
        "AVS":    "info.helvevista@gmail.com",
    }
    saved_emails = _load_case().get("institution_emails", {})
    for actor in Actor:
        if scenario == "revue_avs" and actor != Actor.AVS:
            continue
        if selected.get(actor):
            default_email = saved_emails.get(
                actor.value,
                DEFAULT_INSTITUTION_EMAILS.get(actor.value, ""),
            )
            email = st.text_input(
                f"E-Mail-Adresse der {ACTOR_LABELS[actor]}",
                value=default_email,
                key=f"inst_email_{actor.value}",
                placeholder="info@pensionskasse.ch",
            )
            # Save to case directly without touching session_state widget key
            if email:
                case = _load_case()
                case.setdefault("institution_emails", {})[actor.value] = email
                _save_case(case)

    st.markdown("<div style='height:0.4rem'></div>", unsafe_allow_html=True)

    col_back, col_next = st.columns(2)
    with col_back:
        if st.button("Zurück", use_container_width=True):
            _vs_go(2)
            st.rerun()
    with col_next:
        if st.button("Koordination starten", type="primary", use_container_width=True):
            chosen = {actor for actor, is_checked in selected.items() if is_checked}
            st.session_state.activated_actors = chosen
            case = st.session_state.case
            case["activated_actors"] = [a.value for a in chosen]
            # Read institution emails from case_state.json (already saved by widget handler)
            saved_case = _load_case() or {}
            case["institution_emails"] = saved_case.get("institution_emails", {})
            # Preserve vorsorge_ausweis from existing file if present
            if not case.get("vorsorge_ausweis") and saved_case.get("vorsorge_ausweis"):
                case["vorsorge_ausweis"] = saved_case["vorsorge_ausweis"]
            _save_case(case)
            _vs_go(4)
            st.rerun()


def _vs_step_4_koordination() -> None:
    """
    Step 4 — Koordination läuft.

    Live actor status cards with progress animation.
    Auto-simulation triggers after AUTO_SIM_DELAY seconds if no manual
    institution response is detected in case_state.json.

    Institutional responses simulated via LLM for prototype evaluation purposes.
    To be replaced by real institutional actors in production.
    See Kap. 8 of Bachelor Thesis for academic justification.
    """
    _render_steps(4)

    st.markdown('<div class="hv-label">Schritt 4 von 6</div>', unsafe_allow_html=True)
    st.markdown("## Koordination läuft")

    ctx       = st.session_state.structured_ctx
    activated = st.session_state.activated_actors
    raw       = st.session_state.raw_input

    # ── Initialise orchestrator once ──────────────────────────────────────────
    if st.session_state.orchestrator is None:
        orch    = HelveVistaOrchestrator()
        orch_ctx = {
            **ctx,
            "actors_enum":     list(activated),
            "actors_involved": [a.value for a in activated],
        }
        orch.structure_case(raw_input=raw, structured_context=orch_ctx)
        orch.execute_conditional_fork(activated_actors=activated)
        st.session_state.orchestrator = orch

        # Persist the HelveVista case ID to JSON
        case = st.session_state.case
        case["case_id"] = orch.case_id[:8].upper()
        st.session_state.case = case
        _save_case(case)

    orch: HelveVistaOrchestrator = st.session_state.orchestrator

    # ── Send all requests once ────────────────────────────────────────────────
    if not st.session_state.requests_sent:
        now = time.time()
        for actor in activated:
            orch.send_actor_request(actor, {
                "type":     "initial_request",
                "use_case": ctx.get("use_case", "STELLENWECHSEL"),
            })
        st.session_state.requests_sent = True
        st.session_state.coord_start   = now

        # Persist request metadata to case JSON (for institution dashboard)
        case = _load_case()
        case["requests"] = {
            a.value: {
                "sent_at": now,
                "payload": {"use_case": ctx.get("use_case", "STELLENWECHSEL")},
            }
            for a in activated
        }
        case["orchestrator_state"] = orch.state.value
        _save_case(case)

    # ── Pick up manual institution responses from JSON ────────────────────────
    actors  = orch.actors
    json_case = _load_case()
    inst_resp = json_case.get("institution_responses", {})

    for actor_str, resp in inst_resp.items():
        actor = _actor_from_str(actor_str)
        if (
            actor
            and actor in activated
            and actor not in st.session_state.responses_done
            and actors[actor].state == ActorState.WAITING
        ):
            v = orch.log.current_version
            orch.receive_actor_response(actor, resp, response_version=v)
            st.session_state.responses_done.add(actor)

    actors  = orch.actors   # refresh after potential state changes
    elapsed = time.time() - (st.session_state.coord_start or time.time())

    # ── Actor status cards ────────────────────────────────────────────────────
    st.markdown(
        '<div class="hv-label" style="margin-top:1rem;">Status der Institutionen</div>',
        unsafe_allow_html=True,
    )

    for actor in Actor:
        process = actors[actor]
        state   = process.state
        icon, label, badge_kind = STATE_DISPLAY.get(state, ("—", state.value, "pending"))
        name    = ACTOR_LABELS[actor]

        with st.container(border=True):
            col_name, col_badge = st.columns([3, 1])
            with col_name:
                st.markdown(f"**{name}**")
                if state == ActorState.WAITING:
                    remaining = max(0.0, AUTO_SIM_DELAY - elapsed)
                    if remaining > 0:
                        st.caption(f"Antwort erwartet in {remaining:.0f} Sekunden…")
                    else:
                        st.caption("Antwort wird verarbeitet…")
                elif state == ActorState.SKIPPED:
                    st.caption("Nicht am Prozess beteiligt.")
                elif state == ActorState.COMPLETED:
                    st.caption("Antwort erhalten und validiert.")
                elif state == ActorState.ESCALATED:
                    st.caption("Maximale Wartezeit überschritten — eskaliert.")
                elif state == ActorState.HITL_REQUIRED:
                    st.caption("Ihr Eingriff ist erforderlich.")
            with col_badge:
                st.markdown(
                    _badge(f"{icon} {label}", badge_kind),
                    unsafe_allow_html=True,
                )

    # ── HITL — human-in-the-loop resolution ──────────────────────────────────
    hitl_actors = [
        actor for actor in Actor
        if actor in activated and actors[actor].state == ActorState.HITL_REQUIRED
    ]
    if hitl_actors:
        st.markdown("---")
        st.markdown(
            '<div class="hv-label">Ihr Eingriff ist erforderlich</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            "Bei einer oder mehreren Institutionen wurde ein Daten-Widerspruch erkannt. "
            "Bitte entscheiden Sie, wie weiterverfahren werden soll."
        )
        for actor in hitl_actors:
            with st.container(border=True):
                st.markdown(f"**{ACTOR_LABELS[actor]}** — Widerspruch erkannt")
                st.caption(
                    "Die Institution hat Daten geliefert, die nicht mehr zum aktuellen "
                    "Stand des Falls passen. Sie können die Daten akzeptieren oder "
                    "den Prozess für diese Institution eskalieren."
                )
                col_a, col_b = st.columns(2)
                with col_a:
                    if st.button(
                        "Daten akzeptieren",
                        key=f"hitl_accept_{actor.value}",
                        type="primary",
                        use_container_width=True,
                    ):
                        orch.resolve_hitl(actor, {"action": "accept", "confirmed_by": "user"})
                        st.rerun()
                with col_b:
                    if st.button(
                        "Eskalieren",
                        key=f"hitl_abort_{actor.value}",
                        use_container_width=True,
                    ):
                        orch.abort_hitl(actor)
                        st.rerun()
        return  # wait for all HITL resolution before proceeding

    # ── Auto-simulation of institutional responses ────────────────────────────
    #
    # Institutional responses simulated via LLM for prototype evaluation purposes.
    # To be replaced by real institutional actors in production.
    # See Kap. 8 of Bachelor Thesis for academic justification.
    waiting = [
        actor for actor in Actor
        if actor in activated
        and actors[actor].state == ActorState.WAITING
        and actor not in st.session_state.responses_done
    ]

    auto_sim_enabled = st.session_state.get("auto_sim_enabled", False)

    if waiting and auto_sim_enabled and elapsed >= AUTO_SIM_DELAY:
        # Trigger auto-simulation for all remaining waiting actors
        for actor in waiting:
            resp     = _simulate_response(actor, ctx)
            now_str  = time.strftime("%Y-%m-%dT%H:%M:%S")
            v        = orch.log.current_version
            orch.receive_actor_response(actor, resp, response_version=v)
            st.session_state.responses_done.add(actor)

            # Persist to JSON so institution tab can see the auto-response
            case = _load_case()
            case.setdefault("institution_responses", {})[actor.value]     = resp
            case.setdefault("institution_responded", {})[actor.value]     = True
            case.setdefault("institution_response_date", {})[actor.value] = now_str
            _save_case(case)

        st.rerun()
        return

    if waiting and auto_sim_enabled:
        # Countdown — poll every ~1 s by sleeping briefly then re-running
        st.markdown("---")
        progress_val = min(elapsed / AUTO_SIM_DELAY, 1.0)
        st.progress(progress_val)
        remaining = AUTO_SIM_DELAY - elapsed
        st.caption(
            f"Institutionen wurden benachrichtigt. "
            f"Automatische Simulation in {remaining:.0f} Sekunden, "
            "sofern keine manuelle Antwort über das Institutionen-Portal eingeht."
        )
        time.sleep(1)
        st.rerun()
        return

    if waiting and not auto_sim_enabled:
        # Manual mode — poll every 2 s for institution responses from the portal
        st.markdown("---")

        # ── Phase 2: show pending institution clarification requests ──────────
        manual_case = _load_case()
        pending_clarifs = []
        if pending_clarifs:
            st.markdown(
                '<div style="background:#201800; border:1px solid #3A2800; '
                'border-left:3px solid #C08040; border-radius:4px; '
                'padding:0.8rem 1rem; margin-bottom:0.8rem;">'
                '<div style="color:#C08040; font-size:0.72rem; font-weight:600; '
                'letter-spacing:0.15em; margin-bottom:0.2rem;">'
                'HANDLUNG ERFORDERLICH</div>'
                '<div style="color:#C8D8E8; font-size:0.88rem;">'
                'Eine Institution hat eine Rückfrage gestellt. '
                'Gehen Sie zu Schritt 5 um zu antworten.</div>'
                '</div>',
                unsafe_allow_html=True,
            )

        # ── Email bridge UI ────────────────────────────────────────────────────
        inst_emails = manual_case.get("institution_emails", {})
        case_id     = manual_case.get("case_id", "")

        creds_missing = not (
            __import__("pathlib").Path(__file__).parent.parent.parent
            / "credentials.json"
        ).exists()

        if creds_missing:
            st.warning(
                "Gmail-Konfiguration fehlt. "
                "Bitte credentials.json im Projektverzeichnis ablegen."
            )
        else:
            for actor in sorted(activated, key=lambda a: a.value):
                actor_label = ACTOR_LABELS[actor]
                inst_email  = inst_emails.get(actor.value, "")
                status      = get_email_status(manual_case, actor.value)

                with st.container(border=True):
                    st.markdown(
                        f'<span style="font-weight:500;">{actor_label}</span>',
                        unsafe_allow_html=True,
                    )

                    if status == "not_sent":
                        email_input = st.text_input(
                            "E-Mail-Adresse der Institution",
                            value=inst_email,
                            key=f"email_input_{actor.value}",
                            placeholder="info@pensionskasse.ch",
                        )
                        if st.button(
                            f"E-Mail senden an {actor_label}",
                            key=f"send_email_{actor.value}",
                            use_container_width=True,
                            disabled=not email_input,
                        ):
                            with st.spinner("E-Mail wird gesendet..."):
                                fresh_case = _load_case()
                                ok = send_institution_email(
                                    actor, fresh_case, email_input
                                )
                            if ok:
                                st.success(f"E-Mail gesendet an {email_input}")
                                st.rerun()
                            else:
                                st.error(
                                    "Fehler beim Senden. Bitte prüfen Sie "
                                    "die Gmail-Konfiguration."
                                )

                    elif status == "error":
                        st.error("Senden fehlgeschlagen. Bitte erneut versuchen.")
                        email_input = st.text_input(
                            "E-Mail-Adresse der Institution",
                            value=inst_email,
                            key=f"email_retry_{actor.value}",
                        )
                        if st.button(
                            f"Erneut senden an {actor_label}",
                            key=f"resend_{actor.value}",
                            use_container_width=True,
                            disabled=not email_input,
                        ):
                            with st.spinner("E-Mail wird gesendet..."):
                                fresh_case = _load_case()
                                ok = send_institution_email(
                                    actor, fresh_case, email_input
                                )
                            if ok:
                                st.success(f"E-Mail gesendet an {email_input}")
                                st.rerun()
                            else:
                                st.error(
                                    "Fehler beim Senden. Bitte prüfen Sie "
                                    "die Gmail-Konfiguration."
                                )

                    elif status == "sent":
                        sent_rec = manual_case.get("email_sent", {}).get(actor.value, {})
                        sent_at  = sent_rec.get("sent_at", "")
                        sent_to  = sent_rec.get("to", "")
                        st.info(
                            f"E-Mail gesendet am {sent_at} an {sent_to}\n\n"
                            "Warten auf Antwort..."
                        )
                        if st.button(
                            "Posteingang prüfen",
                            key=f"poll_inbox_{actor.value}",
                            use_container_width=True,
                        ):
                            with st.spinner("Posteingang wird geprüft..."):
                                reply = poll_inbox(case_id, actor.value)
                            if reply is not None:
                                st.success("Antwort erhalten und verarbeitet.")
                                st.rerun()
                            else:
                                st.info(
                                    "Noch keine Antwort. Bitte später prüfen. "
                                    f"(Zuletzt geprüft: {time.strftime('%H:%M:%S')})"
                                )

                    elif status == "replied":
                        parsed = manual_case.get(
                            "institution_responses", {}
                        ).get(actor.value, {})
                        st.success(f"Antwort erhalten von {actor_label}")
                        if "raw_reply" in parsed:
                            st.info(parsed["raw_reply"])
                        else:
                            for k, v in parsed.items():
                                st.caption(f"{k}: {v}")

        # Advance automatically once all activated actors have replied via email
        all_responded = all(
            get_email_status(manual_case, a.value) == "replied"
            for a in activated
        )
        if all_responded:
            st.rerun()
        else:
            time.sleep(2)
            st.rerun()
        return

    # ── All actors terminal → ready to proceed ────────────────────────────────
    if orch.state == OrchestratorState.USER_VALIDATION:
        any_esc = any(
            p.state == ActorState.ESCALATED
            for p in actors.values()
            if p.state != ActorState.SKIPPED
        )
        st.markdown("---")
        if any_esc:
            st.warning(
                "Eine oder mehrere Institutionen haben nicht vollständig geantwortet."
            )
        else:
            st.success("Alle Institutionen haben erfolgreich geantwortet.")

        # Sync final actor states to JSON
        case = _load_case()
        case["orchestrator_state"] = orch.state.value
        case["actor_states"]       = {a.value: p.state.value for a, p in actors.items()}
        _save_case(case)

        col_back, col_next = st.columns(2)
        with col_back:
            if st.button("Zurück", use_container_width=True):
                _vs_go(3)
                st.rerun()
        with col_next:
            if st.button("Ergebnisse anzeigen", type="primary", use_container_width=True):
                _vs_go(5)
                st.rerun()


def _vs_step_5_ergebnis() -> None:
    """Step 5 — Ergebnis: summary cards per actor with response details"""
    _render_steps(5)

    st.markdown('<div class="hv-label">Schritt 5 von 6</div>', unsafe_allow_html=True)
    st.markdown("## Ergebnis der Koordination")

    orch: HelveVistaOrchestrator = st.session_state.orchestrator
    actors    = orch.actors
    activated = st.session_state.activated_actors
    ctx       = st.session_state.structured_ctx

    # Load institution responses from JSON (may include manual responses)
    case      = _load_case()
    inst_resp = case.get("institution_responses", {})
    vorsorge  = case.get("vorsorge_ausweis", {})  # PDF-extracted data as fallback
    # Normalize: unwrap actor-keyed nesting if LLM returned {actor_key: {...}} format
    inst_resp = {
        ak: (v[ak] if isinstance(v, dict) and isinstance(v.get(ak), dict) else v)
        for ak, v in inst_resp.items()
    }

    # ── Phase 2: show pending institution clarification requests first ─────────
    _render_pending_clarifications(case)

    # LLM-generated case summary (once)
    if st.session_state.llm_summary is None and _use_llm():
        with st.spinner("Zusammenfassung wird erstellt…"):
            try:
                import anthropic as _anthropic  # noqa: PLC0415
                _client = _anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
                _old_pk = inst_resp.get(Actor.OLD_PK.value, {})
                _new_pk = inst_resp.get(Actor.NEW_PK.value, {})
                _avs    = inst_resp.get(Actor.AVS.value, {})
                # Prefer institution response values; fall back to vorsorge_ausweis
                _freizuegigkeit_chf = (
                    _old_pk.get("freizuegigkeit_chf")
                    or vorsorge.get("freizuegigkeit_chf")
                    or vorsorge.get("gesamtguthaben_chf")
                )
                _austrittsdatum = _old_pk.get("austrittsdatum")
                _status_old     = _old_pk.get("status")
                _eintrittsdatum = _new_pk.get("eintrittsdatum")
                _bvg_koord = (
                    _new_pk.get("bvg_koordinationsabzug")
                    or vorsorge.get("koordinationsabzug_chf")
                    or vorsorge.get("bvg_koordinationsabzug")
                )
                _bvg_pflicht    = _new_pk.get("bvg_pflicht")
                _beitragsjahre  = _avs.get("beitragsjahre")
                _avs_status     = _avs.get("status")
                _user_name      = case.get("user_name", "—")
                avs_line = (
                    f"- AHV-Beitragsjahre: {_beitragsjahre or 'nicht angegeben'}"
                    if _avs else ""
                )
                _user_msg = (
                    f"Name des Versicherten: {_user_name}\n\n"
                    f"Originale Situation: {case.get('situation', '—')}\n\n"
                    f"Antwort Alte Pensionskasse:\n"
                    f"  - freizuegigkeit_chf: {_freizuegigkeit_chf}\n"
                    f"  - austrittsdatum: {_austrittsdatum}\n"
                    f"  - status: {_status_old}\n\n"
                    f"Antwort Neue Pensionskasse:\n"
                    f"  - eintrittsdatum: {_eintrittsdatum}\n"
                    f"  - bvg_koordinationsabzug: {_bvg_koord}\n"
                    f"  - bvg_pflicht: {_bvg_pflicht}"
                    + (
                        f"\n\nAntwort AHV-Ausgleichskasse:\n"
                        f"  - beitragsjahre: {_beitragsjahre}\n"
                        f"  - status: {_avs_status}"
                        if _avs else ""
                    )
                )
                _resp = _client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=512,
                    system=(
                        f"Du bist HelveVista. Schreibe eine präzise, persönliche Zusammenfassung "
                        f"in 3-4 Sätzen für {_user_name}.\n"
                        "Verwende NUR die folgenden Daten — erfinde NICHTS:\n"
                        f"- Freizügigkeitsguthaben: {_freizuegigkeit_chf or 'nicht angegeben'}\n"
                        f"- Austrittsdatum: {_austrittsdatum or 'nicht angegeben'}\n"
                        f"- Eintrittsdatum: {_eintrittsdatum or 'nicht angegeben'}\n"
                        f"- BVG-Koordinationsabzug: {_bvg_koord or 'nicht angegeben'}\n"
                        + (f"{avs_line}\n" if avs_line else "")
                        + "Wenn ein Wert 'nicht angegeben' ist, erwähne ihn NICHT. "
                        "Schreibe in der Du-Form, professionell und klar."
                    ),
                    messages=[{"role": "user", "content": _user_msg}],
                )
                st.session_state.llm_summary = _resp.content[0].text.strip()
            except Exception:
                _old_pk = inst_resp.get(Actor.OLD_PK.value, {})
                _new_pk = inst_resp.get(Actor.NEW_PK.value, {})
                _name = case.get("user_name", "Versicherte/r")
                _chf = (
                    _old_pk.get("freizuegigkeit_chf")
                    or vorsorge.get("freizuegigkeit_chf")
                    or vorsorge.get("gesamtguthaben_chf")
                )
                _datum = _new_pk.get("eintrittsdatum", "—")
                st.session_state.llm_summary = (
                    f"Liebe/r {_name}, Ihr Stellenwechsel wurde koordiniert. "
                    + (f"Ihr Freizügigkeitsguthaben von {_fmt_chf(_chf)} wird übertragen. " if isinstance(_chf, (int, float)) else "")
                    + (f"Ihr Eintritt bei der neuen Pensionskasse ist per {_datum} bestätigt." if _datum and _datum != "—" else "")
                )

    if st.session_state.llm_summary:
        st.info(st.session_state.llm_summary)

    # Actor result cards
    st.markdown(
        '<div class="hv-label" style="margin-top:1rem;">Antworten der Institutionen</div>',
        unsafe_allow_html=True,
    )

    non_skipped = [a for a in Actor if actors[a].state != ActorState.SKIPPED]
    for actor in non_skipped:
        process = actors[actor]
        state   = process.state
        _, label, badge_kind = STATE_DISPLAY.get(state, ("—", state.value, "pending"))
        name    = ACTOR_LABELS[actor]
        resp    = inst_resp.get(actor.value, {})

        with st.container(border=True):
            col_h, col_b = st.columns([3, 1])
            with col_h:
                st.markdown(f"**{name}**")
            with col_b:
                st.markdown(_badge(label, badge_kind), unsafe_allow_html=True)

            if state == ActorState.COMPLETED and resp:
                st.markdown("<div style='height:0.3rem'></div>", unsafe_allow_html=True)

                def _gold(label: str, value: str) -> None:
                    st.markdown(
                        f'<span style="color:#C9A84C;font-weight:600;">{label}:</span> {value}',
                        unsafe_allow_html=True,
                    )

                if actor == Actor.OLD_PK:
                    case = _load_case()
                    inst_resp = case.get("institution_responses", {})
                    vorsorge = case.get("vorsorge_ausweis", {})
                    chf = (
                        resp.get("freizuegigkeit_chf")
                        or vorsorge.get("freizuegigkeit_chf")
                        or vorsorge.get("gesamtguthaben_chf")
                    )
                    _gold("Freizügigkeitsguthaben", _fmt_chf(chf))
                    _gold("Austrittsdatum", _fmt_date(resp.get("austrittsdatum")))
                    _gold("Status", _fmt_status(resp.get("status")))

                elif actor == Actor.NEW_PK:
                    koord = (
                        resp.get("bvg_koordinationsabzug")
                        or vorsorge.get("koordinationsabzug_chf")
                        or vorsorge.get("bvg_koordinationsabzug")
                    )
                    _gold("Eintrittsdatum", _fmt_date(resp.get("eintrittsdatum")))
                    _gold("BVG-Koordinationsabzug", _fmt_chf(koord))
                    _gold("BVG-Pflicht", "Ja" if resp.get("bvg_pflicht") else "Nein")

                elif actor == Actor.AVS:
                    ik_ok = resp.get("ik_auszug_verfuegbar") or (resp.get("ik_auszug") == "verfügbar")
                    _gold("IK-Auszug verfügbar", "Ja" if ik_ok else "Nein")
                    ahv = resp.get("ahv_nummer") or vorsorge.get("ahv_nummer")
                    if ahv:
                        _gold("AHV-Nummer", str(ahv))
                    jahre = resp.get("beitragsjahre")
                    _gold("Beitragsjahre", _fmt_str(jahre))
                    luecken = resp.get("luecken")
                    if luecken is not None:
                        _gold("Beitragslücken", str(luecken))
                    status_avs = resp.get("status")
                    if status_avs:
                        _gold("Status", str(status_avs))

            elif state == ActorState.ESCALATED:
                st.caption("Keine gültige Antwort erhalten — Eskalation ist erforderlich.")

    # ── Plain language summaries + follow-up actions ───────────────────────────
    completed_actors = [
        a for a in non_skipped
        if actors[a].state == ActorState.COMPLETED
    ]
    if completed_actors:
        st.markdown("---")
        st.markdown(
            '<div class="hv-label">Was bedeutet das für Sie?</div>',
            unsafe_allow_html=True,
        )
        fresh_case        = _load_case()
        follow_up_reqs    = fresh_case.get("follow_up_requests", {})
        follow_up_ques    = fresh_case.get("follow_up_questions", {})
        user_name_display = fresh_case.get("user_name", st.session_state.user_name)

        for actor in completed_actors:
            resp = inst_resp.get(actor.value) or DEMO_RESPONSES.get(actor, {})
            name = ACTOR_LABELS[actor]

            # Build actor-specific explanation and document name
            if actor == Actor.OLD_PK:
                chf     = resp.get("freizuegigkeit_chf")
                chf_fmt = _fmt_chf(chf)
                chf_clause = f"von **{chf_fmt}** " if isinstance(chf, (int, float)) else ""
                explanation = (
                    f"Ihre alte Pensionskasse hat Ihr Freizügigkeitsguthaben "
                    f"{chf_clause}bestätigt. "
                    f"Dieses Guthaben wird automatisch auf Ihre neue Pensionskasse "
                    f"übertragen. Sie müssen nichts weiter unternehmen."
                )
                doc_name = "Freizügigkeitsabrechnung"

            elif actor == Actor.NEW_PK:
                datum = resp.get("eintrittsdatum")
                koord = resp.get("bvg_koordinationsabzug")
                koord_fmt = _fmt_chf(koord)
                if datum and str(datum) not in ("None", "null", "—", ""):
                    datum_clause = f"Ihren Eintritt per **{datum}** bestätigt"
                else:
                    datum_clause = "Ihren Eintritt zum vereinbarten Eintrittsdatum bestätigt"
                if isinstance(koord, (int, float)):
                    koord_clause = f"Der BVG-Koordinationsabzug beträgt **{koord_fmt}**. "
                else:
                    koord_clause = ""
                explanation = (
                    f"Ihre neue Pensionskasse hat {datum_clause}. "
                    f"{koord_clause}"
                    f"Bewahren Sie die Eingangsbestätigung für Ihre Unterlagen auf."
                )
                doc_name = "Eingangsbestätigung"

            else:  # AVS
                jahre  = resp.get("beitragsjahre")
                if jahre:
                    explanation = (
                        f"Die AHV-Ausgleichskasse hat Ihren IK-Auszug bereitgestellt. "
                        f"Sie verfügen über {jahre} Beitragsjahre. "
                        f"Dieser Auszug ist massgebend für die Berechnung Ihrer "
                        f"künftigen AHV-Rente."
                    )
                else:
                    explanation = (
                        "Die AHV-Ausgleichskasse hat Ihren IK-Auszug bereitgestellt. "
                        "Dieser Auszug dokumentiert Ihre bisherigen AHV-Beitragsjahre "
                        "und ist massgebend für Ihre künftige Rentenberechnung."
                    )
                doc_name = "IK-Auszug"

            st.markdown(
                f'<div class="hv-label" style="margin-top:0.8rem;">{name}</div>',
                unsafe_allow_html=True,
            )
            st.info(explanation)

            col_a, col_b = st.columns(2)

            with col_a:
                doc_status = get_followup_status(fresh_case, actor.value, "dokument")
                if doc_status == "replied":
                    reply_info = (
                        fresh_case.get("follow_up_replies", {})
                                  .get(actor.value, {})
                                  .get("dokument", {})
                    )
                    st.success(f"Antwort erhalten von {name}")
                    st.text_area(
                        "Antworttext",
                        value=reply_info.get("reply_text", ""),
                        height=120,
                        disabled=True,
                        key=f"doc_reply_{actor.value}",
                    )
                elif doc_status == "sent":
                    sent_at = (
                        fresh_case.get("follow_up_requests", {})
                                  .get(actor.value, {})
                                  .get("sent_at", "")
                    )
                    st.info(f"E-Mail gesendet am {sent_at} — Warten auf Antwort...")
                    if st.button(
                        "Posteingang prüfen",
                        key=f"doc_poll_{actor.value}",
                        use_container_width=True,
                    ):
                        c = _load_case()
                        with st.spinner("Posteingang wird geprüft..."):
                            reply = poll_followup_inbox(c, actor.value, "dokument")
                        if reply is not None:
                            st.success("Antwort erhalten.")
                        else:
                            st.info("Noch keine Antwort. Bitte später prüfen.")
                        st.rerun()
                else:  # not_sent
                    with st.expander("Dokument anfordern"):
                        pre_text = (
                            f"Sehr geehrte Damen und Herren,\n\n"
                            f"ich bitte um Zustellung folgender Unterlagen: {doc_name}. "
                            f"Bitte senden Sie diese an meine Adresse.\n\n"
                            f"Mit freundlichen Grüssen,\n{user_name_display}"
                        )
                        edited_text = st.text_area(
                            "Anfragetext",
                            value=pre_text,
                            height=160,
                            key=f"doc_text_{actor.value}",
                            label_visibility="collapsed",
                        )
                        if st.button(
                            "Anfrage senden",
                            key=f"doc_send_{actor.value}",
                            type="primary",
                            use_container_width=True,
                        ):
                            c = _load_case()
                            inst_email_addr = c.get("institution_emails", {}).get(actor.value, "")
                            case_id = c.get("case_id", "UNKNOWN")
                            email_subject = (
                                f"HelveVista \u2014 Dokumentenanfrage {name} \u2014 Fall {case_id[:8]}"
                            )
                            with st.spinner("E-Mail wird gesendet..."):
                                ok = send_followup_email(inst_email_addr, email_subject, edited_text) if inst_email_addr else False
                            if ok:
                                c.setdefault("follow_up_requests", {})[actor.value] = {
                                    "text":    edited_text,
                                    "sent_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                }
                                _save_case(c)
                                st.success("Anfrage gesendet.")
                            else:
                                st.error("Fehler beim Senden. Bitte prüfen Sie die Gmail-Konfiguration oder ob eine Institutions-E-Mail hinterlegt ist.")
                            st.rerun()

            with col_b:
                ques_status = get_followup_status(fresh_case, actor.value, "rueckfrage")
                if ques_status == "replied":
                    reply_info = (
                        fresh_case.get("follow_up_replies", {})
                                  .get(actor.value, {})
                                  .get("rueckfrage", {})
                    )
                    st.success(f"Antwort erhalten von {name}")
                    st.text_area(
                        "Antworttext",
                        value=reply_info.get("reply_text", ""),
                        height=120,
                        disabled=True,
                        key=f"ques_reply_{actor.value}",
                    )
                elif ques_status == "sent":
                    questions = fresh_case.get("follow_up_questions", {}).get(actor.value, [])
                    sent_at   = questions[-1]["sent_at"] if questions else ""
                    st.info(f"E-Mail gesendet am {sent_at} — Warten auf Antwort...")
                    if st.button(
                        "Posteingang prüfen",
                        key=f"ques_poll_{actor.value}",
                        use_container_width=True,
                    ):
                        c = _load_case()
                        with st.spinner("Posteingang wird geprüft..."):
                            reply = poll_followup_inbox(c, actor.value, "rueckfrage")
                        if reply is not None:
                            st.success("Antwort erhalten.")
                        else:
                            st.info("Noch keine Antwort. Bitte später prüfen.")
                        st.rerun()
                else:  # not_sent
                    with st.expander("Rückfrage stellen"):
                        question = st.text_area(
                            f"Ihre Frage an {name}",
                            placeholder=f"Schreiben Sie Ihre Frage an die {name}…",
                            height=120,
                            key=f"ques_text_{actor.value}",
                            label_visibility="visible",
                        )
                        if st.button(
                            "Frage senden",
                            key=f"ques_send_{actor.value}",
                            type="primary",
                            use_container_width=True,
                        ):
                            if question.strip():
                                c = _load_case()
                                inst_email_addr = c.get("institution_emails", {}).get(actor.value, "")
                                case_id = c.get("case_id", "UNKNOWN")
                                email_subject = (
                                    f"HelveVista \u2014 Rückfrage {name} \u2014 Fall {case_id[:8]}"
                                )
                                with st.spinner("E-Mail wird gesendet..."):
                                    ok = send_followup_email(inst_email_addr, email_subject, question.strip()) if inst_email_addr else False
                                if ok:
                                    c.setdefault("follow_up_questions", {}).setdefault(
                                        actor.value, []
                                    ).append({
                                        "question": question.strip(),
                                        "sent_at":  time.strftime("%Y-%m-%dT%H:%M:%S"),
                                    })
                                    _save_case(c)
                                    st.success("Rückfrage gesendet.")
                                else:
                                    st.error("Fehler beim Senden. Bitte prüfen Sie die Gmail-Konfiguration oder ob eine Institutions-E-Mail hinterlegt ist.")
                                st.rerun()
                            else:
                                st.warning("Bitte geben Sie Ihre Frage ein.")

    # ── Phase 2: full conversation timeline ───────────────────────────────────
    fresh_case_for_timeline = _load_case()
    timeline_events = []
    if len(timeline_events) > 1:   # more than just "Fall eröffnet"
        st.markdown("---")
        st.markdown(
            '<div class="hv-label">Kommunikationsverlauf</div>',
            unsafe_allow_html=True,
        )
        _render_conversation_timeline(fresh_case_for_timeline)

    # HelveVista clarification chat (H3 — Perceived Support)
    _render_chat_section(case, section_key="step5")

    st.markdown("<div style='height:0.4rem'></div>", unsafe_allow_html=True)

    col_back, col_next = st.columns(2)
    with col_back:
        if st.button("Zurück", use_container_width=True):
            _vs_go(4)
            st.rerun()
    with col_next:
        if st.button("Zum Entscheid", type="primary", use_container_width=True):
            _vs_go(6)
            st.rerun()


def _vs_step_6_entscheid() -> None:
    """Step 6 — Entscheid: 3 action buttons"""
    _render_steps(6)

    st.markdown('<div class="hv-label">Schritt 6 von 6</div>', unsafe_allow_html=True)
    st.markdown("## Ihr Entscheid")

    orch: HelveVistaOrchestrator = st.session_state.orchestrator
    actors = orch.actors

    any_esc = any(
        p.state == ActorState.ESCALATED
        for p in actors.values()
        if p.state != ActorState.SKIPPED
    )

    if any_esc:
        st.warning(
            "Empfehlung: Eskalieren — eine oder mehrere Institutionen haben nicht "
            "vollständig geantwortet. Ein Berater wird den Fall weiterbearbeiten."
        )
    else:
        st.success(
            "Empfehlung: Abschliessen — alle Institutionen haben erfolgreich geantwortet. "
            "Ihr Stellenwechsel kann abgeschlossen werden."
        )

    st.markdown(
        "Bitte treffen Sie Ihren abschliessenden Entscheid. "
        "Diese Aktion schliesst den Fall und kann nicht rückgängig gemacht werden."
    )

    st.markdown("<div style='height:0.6rem'></div>", unsafe_allow_html=True)

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("Abschliessen", type="primary", use_container_width=True):
            orch.validate_and_close("accept")
            case = _load_case()
            case["final_decision"]    = "accept"
            case["orchestrator_state"] = "CLOSED_SUCCESS"
            _save_case(case)
            _vs_go(7)
            st.rerun()

    with col2:
        if st.button("Eskalieren", use_container_width=True):
            orch.validate_and_close("escalate")
            case = _load_case()
            case["final_decision"]    = "escalate"
            case["orchestrator_state"] = "CLOSED_ESCALATED"
            _save_case(case)
            _vs_go(7)
            st.rerun()

    with col3:
        if st.button("Abbrechen", use_container_width=True):
            orch.validate_and_close("abort")
            case = _load_case()
            case["final_decision"]    = "abort"
            case["orchestrator_state"] = "CLOSED_ABORTED"
            _save_case(case)
            _vs_go(7)
            st.rerun()

    # HelveVista clarification chat (H3 — Perceived Support)
    _render_chat_section(_load_case(), section_key="step6")

    st.markdown("<div style='height:0.4rem'></div>", unsafe_allow_html=True)

    col_back, _ = st.columns([1, 2])
    with col_back:
        if st.button("Zurück", use_container_width=True):
            _vs_go(5)
            st.rerun()


def _vs_step_final() -> None:
    """Final screen — confirmation with case ID and next steps"""
    orch: HelveVistaOrchestrator = st.session_state.orchestrator
    final = orch.state

    if final == OrchestratorState.CLOSED_SUCCESS:
        st.balloons()
        st.markdown(
            """
            <div class="hv-confirm">
              <div class="icon" style="color:#4CAF82;">✓</div>
              <div class="title">Stellenwechsel abgeschlossen</div>
              <div class="sub">Ihr Vorsorgedossier wurde erfolgreich koordiniert.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        next_steps = [
            "Ihr Freizügigkeitsguthaben wird automatisch zur neuen Pensionskasse übertragen.",
            "Die neue Pensionskasse bestätigt die Anmeldung schriftlich innerhalb von 14 Tagen.",
            "Sie erhalten eine vollständige Zusammenfassung per Post.",
        ]

    elif final == OrchestratorState.CLOSED_ESCALATED:
        st.markdown(
            """
            <div class="hv-confirm">
              <div class="icon" style="color:#C9A84C;">↑</div>
              <div class="title">Fall eskaliert</div>
              <div class="sub">Ein Berater wird sich mit Ihnen in Verbindung setzen.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        next_steps = [
            "Ein Berater prüft den Fall und kontaktiert Sie innerhalb von 3 Werktagen.",
            "Alle bisherigen Schritte sind im Ereignisprotokoll vollständig gesichert.",
            "Sie können den Status jederzeit in HelveVista verfolgen.",
        ]

    else:  # CLOSED_ABORTED
        st.markdown(
            """
            <div class="hv-confirm">
              <div class="icon" style="color:#CF6679;">×</div>
              <div class="title">Vorgang abgebrochen</div>
              <div class="sub">Keine Änderungen wurden vorgenommen.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        next_steps = [
            "Der Vorgang wurde ohne Änderungen an Ihren Vorsorgeguthaben beendet.",
            "Alle Daten bleiben unverändert.",
            "Sie können jederzeit einen neuen Antrag stellen.",
        ]

    # Email summary notification (simulated — no real send)
    if final in (OrchestratorState.CLOSED_SUCCESS, OrchestratorState.CLOSED_ESCALATED):
        user_email_display = st.session_state.get("user_email", "") or _load_case().get("user_email", "")
        if user_email_display:
            st.markdown(
                f'<div style="text-align:center; color:#5A7A9A; font-size:0.85rem; margin-bottom:1rem;">'
                f"Eine Zusammenfassung wird an <strong>{user_email_display}</strong> gesendet."
                f"</div>",
                unsafe_allow_html=True,
            )

    # Case metadata
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Fall-ID", orch.case_id[:8].upper())
    with col2:
        st.metric("Protokollierte Ereignisse", orch.log.current_version)

    # Next steps
    st.markdown("---")
    st.markdown('<div class="hv-label">Nächste Schritte</div>', unsafe_allow_html=True)
    for step in next_steps:
        st.markdown(f"&nbsp;&nbsp;· {step}")

    # Append-only event log (collapsible)
    st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)
    with st.expander("Ereignisprotokoll anzeigen"):
        st.caption(
            "Jeder Schritt des Prozesses wurde unveränderlich protokolliert "
            "(Append-only Event Log, HelveVista Modell V2)."
        )
        for event in orch.log.events:
            ts     = event.timestamp[:19].replace("T", " ")
            from_s = event.payload.get("from", "")
            to_s   = event.payload.get("to",   "")
            arrow  = f" `{from_s}` → `{to_s}`" if from_s and to_s else ""
            st.markdown(f"`{ts}` **{event.actor}** — {event.event_type}{arrow}")

    st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)

    if st.button("Neuen Antrag stellen", type="primary", use_container_width=True):
        # Remove shared JSON and fully reset session
        if CASE_FILE.exists():
            CASE_FILE.unlink()
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        _init_session()
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# HELVEVISTA CLARIFICATION CHAT (H3 — Perceived Support)
# ══════════════════════════════════════════════════════════════════════════════

_DEMO_FALLBACK_ANSWER = (
    "Ihre Frage geht über die Angaben in Ihrem Fall hinaus. "
    "Bitte wenden Sie sich direkt an die zuständige Institution "
    "über die Schaltfläche 'Rückfrage stellen' oben."
)


def _chat_llm_answer(question: str, case: dict) -> str:
    """Call Claude API with full case context incl. situation + vorsorge_ausweis."""
    import anthropic

    user_name        = case.get("user_name", "")
    situation_text   = case.get("situation", "")
    vorsorge         = case.get("vorsorge_ausweis", {})
    inst_responses   = case.get("institution_responses", {})
    actors_data      = case.get("actors", {})
    sparring_data    = case.get(
        "sparring_collected",
        st.session_state.get("sparring_collected", {}),
    )

    system_prompt = f"""Du bist HelveVista, ein Schweizer Vorsorge-Assistent.
Du beantwortest Fragen des Versicherten zu seinem konkreten Fall. Antworte ausschliesslich auf Deutsch.

FALLDATEN:
Versicherter: {user_name}
Situation: {situation_text}

VORSORGEAUSWEIS-DATEN:
{json.dumps(vorsorge, ensure_ascii=False, indent=2)}

ANTWORTEN DER INSTITUTIONEN:
{json.dumps(inst_responses, ensure_ascii=False, indent=2)}

KOORDINATIONSSTATUS:
{json.dumps(actors_data, ensure_ascii=False, indent=2)}

GESAMMELTE INFORMATIONEN (Sparring):
{json.dumps(sparring_data, ensure_ascii=False, indent=2)}

REGELN:
1. Beantworte NUR Fragen die sich auf diesen Fall beziehen
2. Nutze die obigen Daten um konkrete, genaue Antworten zu geben
3. Wenn eine Information wirklich nicht im Fall vorhanden ist, sage es klar — aber prüfe ALLE Datenfelder zuerst
4. Antworte präzise und hilfreich — keine generischen Antworten, max 2-3 Sätze
5. Verwende CHF-Beträge und Daten aus den Falldaten wenn vorhanden
6. Trigger AUSSERHALB_DES_FALLS NUR wenn die Frage wirklich nichts mit diesem konkreten Fall zu tun hat"""
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    msg = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=256,
        system=system_prompt,
        messages=[{"role": "user", "content": question}],
    )
    return msg.content[0].text.strip()


def _chat_demo_answer(question: str, case: dict) -> str:
    """Return a smart keyword-matched demo answer using actual case data."""
    q_lower = question.lower()

    inst_resp   = case.get("institution_responses", {})
    actor_states = case.get("actor_states", {})

    old_pk = inst_resp.get("OLD_PK", DEMO_RESPONSES.get(Actor.OLD_PK, {}))
    new_pk = inst_resp.get("NEW_PK", DEMO_RESPONSES.get(Actor.NEW_PK, {}))
    avs    = inst_resp.get("AVS",    DEMO_RESPONSES.get(Actor.AVS,    {}))

    freizuegigkeit_chf    = old_pk.get("freizuegigkeit_chf")
    freizuegigkeit_fmt    = _fmt_chf(freizuegigkeit_chf)
    bvg_koordinationsabzug = new_pk.get("bvg_koordinationsabzug")
    koord_fmt             = _fmt_chf(bvg_koordinationsabzug)
    eintrittsdatum        = new_pk.get("eintrittsdatum", "—")
    beitragsjahre         = avs.get("beitragsjahre", "—")

    completed = [
        ACTOR_LABELS[_actor_from_str(a)]  # type: ignore[arg-type]
        for a, s in actor_states.items()
        if s == "COMPLETED" and _actor_from_str(a) is not None
    ]

    if any(kw in q_lower for kw in ("koordinationsabzug", "koordination", "abzug")):
        return (
            f"Der BVG-Koordinationsabzug beträgt für Ihren Fall **{koord_fmt}**. "
            "Dieser gesetzlich festgelegte Betrag wird jährlich vom Bundesrat festgesetzt und "
            "vor der BVG-Beitragsberechnung vom versicherten Lohn abgezogen."
        )

    if any(kw in q_lower for kw in ("freizügigkeit", "guthaben", "übertrag", "transfer")):
        return (
            f"Ihr Freizügigkeitsguthaben von **{freizuegigkeit_fmt}** wird automatisch "
            "von Ihrer alten an Ihre neue Pensionskasse übertragen. "
            "Sie müssen nichts selbst veranlassen."
        )

    if any(kw in q_lower for kw in ("karriere", "jährlich", "pro jahr", "laufzeit")):
        return (
            f"Das Freizügigkeitsguthaben von **{freizuegigkeit_fmt}** ist der Gesamtbetrag, "
            "der über Ihre bisherige Karriere angespart wurde — nicht ein Jahresbetrag. "
            "Es wächst jedes Jahr durch Arbeitgeber- und Arbeitnehmerbeiträge."
        )

    if any(kw in q_lower for kw in ("bvg", "pflicht", "versichert")):
        return (
            "BVG-Pflicht bedeutet, dass Ihr neuer Arbeitgeber Sie ab dem ersten Arbeitstag "
            f"versichern muss (Eintrittsdatum: **{eintrittsdatum}**). "
            "Dies ist gesetzlich vorgeschrieben."
        )

    if any(kw in q_lower for kw in ("ahv", "ik", "auszug", "beitragsjahre")):
        return (
            f"Der IK-Auszug zeigt **{beitragsjahre}** Beitragsjahre. "
            "Diese Zahl bestimmt die Höhe Ihrer zukünftigen AHV-Rente."
        )

    if any(kw in q_lower for kw in ("nächste schritte", "was muss", "was soll", "was tun")):
        steps = [
            "Ihr Freizügigkeitsguthaben wird automatisch übertragen — keine Aktion nötig.",
            "Bewahren Sie die Eingangsbestätigung der neuen Pensionskasse auf.",
            "Kontrollieren Sie Ihren ersten Lohnausweis auf den korrekten BVG-Abzug.",
        ]
        return " · ".join(steps)

    return _DEMO_FALLBACK_ANSWER


def _render_chat_section(case: dict, section_key: str) -> None:
    """
    Render the HelveVista clarification chat at the bottom of a results step.
    section_key is used to namespace Streamlit widget keys.
    """
    MAX_QUESTIONS = 5

    st.markdown("---")
    st.markdown(
        '<div class="hv-label">Haben Sie eine Frage zu Ihrem Ergebnis?</div>',
        unsafe_allow_html=True,
    )

    history: list[dict] = st.session_state.chat_history

    # Display previous Q&As
    if history:
        for i, qa in enumerate(history):
            with st.container(border=True):
                st.markdown(
                    f'<span style="color:#C9A84C; font-weight:600;">Sie:</span> {qa["question"]}',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    '<hr style="border:none; border-top:1px solid #1A3048; margin:0.5rem 0;">',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f'<span style="color:#6A9ABE; font-weight:600;">HelveVista:</span> {qa["answer"]}',
                    unsafe_allow_html=True,
                )
                # Guardrail: out-of-scope → show contact button
                if "AUSSERHALB_DES_FALLS" in qa["answer"] or _DEMO_FALLBACK_ANSWER in qa["answer"]:
                    st.markdown(
                        "Für weitere Fragen wenden Sie sich direkt an die zuständige Institution:"
                    )
                    non_skipped_vals = [
                        a for a in case.get("activated_actors", [])
                    ]
                    if non_skipped_vals:
                        actor_val = non_skipped_vals[0]
                        label = ACTOR_LABELS.get(
                            _actor_from_str(actor_val),  # type: ignore[arg-type]
                            actor_val,
                        )
                        if st.button(
                            f"Rückfrage stellen ({label})",
                            key=f"chat_contact_{section_key}_{i}",
                        ):
                            st.session_state.vs_step = 5
                            st.rerun()

    remaining = MAX_QUESTIONS - len(history)

    if remaining <= 0:
        st.caption(
            "Sie haben die maximale Anzahl von 5 Fragen pro Sitzung erreicht. "
            "Für weitere Informationen wenden Sie sich an die zuständige Institution."
        )
    else:
        col_q, col_btn = st.columns([5, 1])
        with col_q:
            question = st.text_input(
                "Frage",
                placeholder="Stellen Sie HelveVista eine Frage zu Ihren Ergebnissen…",
                key=f"chat_input_{section_key}",
                label_visibility="collapsed",
            )
        with col_btn:
            ask = st.button("Fragen", key=f"chat_btn_{section_key}", type="primary")

        if ask:
            if not question.strip():
                st.warning("Bitte geben Sie Ihre Frage ein.")
            else:
                with st.spinner("HelveVista antwortet…"):
                    try:
                        if _use_llm():
                            answer = _chat_llm_answer(question.strip(), case)
                        else:
                            answer = _chat_demo_answer(question.strip(), case)
                    except Exception:
                        answer = _chat_demo_answer(question.strip(), case)
                st.session_state.chat_history.append(
                    {"question": question.strip(), "answer": answer}
                )
                st.rerun()

        st.caption(
            "HelveVista beantwortet nur Fragen zu Ihrem aktuellen Fall. "
            "Für allgemeine Vorsorgeberatung wenden Sie sich an einen Fachberater."
        )
        if remaining < MAX_QUESTIONS:
            st.caption(f"Noch {remaining} Frage(n) verfügbar.")


# ══════════════════════════════════════════════════════════════════════════════
# INSTITUTION FLOW — Dashboard, Form, Done
# ══════════════════════════════════════════════════════════════════════════════

_ACTOR_REQUEST_LABEL: dict[Actor, str] = {
    Actor.OLD_PK: "Freizügigkeitsabrechnung",
    Actor.NEW_PK: "Eintrittsbestätigung",
    Actor.AVS:    "IK-Auszug",
}

_ACTOR_REQUEST_FIELDS: dict[Actor, str] = {
    Actor.OLD_PK: "Freizügigkeitsguthaben (CHF) · Austrittsdatum · Statusbestätigung",
    Actor.NEW_PK: "Eintrittsdatum · BVG-Koordinationsabzug (CHF) · BVG-Pflicht",
    Actor.AVS:    "IK-Auszug Verfügbarkeit · Beitragsjahre · Lückenjahre",
}

_ACTOR_EMAIL_SUBJECT: dict[Actor, str] = {
    Actor.OLD_PK: "Anfrage Freizügigkeitsabrechnung",
    Actor.NEW_PK: "Anfrage Eintrittsbestätigung",
    Actor.AVS:    "Anfrage IK-Auszug",
}

_ACTOR_EMAIL_BODY: dict[Actor, str] = {
    Actor.OLD_PK: (
        "wir koordinieren im Auftrag des/der nachfolgend genannten Versicherten "
        "den Austritt aus Ihrer Pensionskasse im Rahmen eines Stellenwechsels.\n\n"
        "Wir bitten Sie, folgende Angaben zu übermitteln:\n"
        "  · Freizügigkeitsguthaben per Austrittsdatum (CHF)\n"
        "  · Austrittsdatum (TT. Monat JJJJ)\n"
        "  · Statusbestätigung des Austritts\n\n"
        "Die Angaben dienen der automatischen Koordination des Guthaben-Transfers "
        "zur neuen Pensionskasse gemäss Art. 3 ff. FZG."
    ),
    Actor.NEW_PK: (
        "wir koordinieren im Auftrag des/der nachfolgend genannten Versicherten "
        "den Eintritt in Ihre Pensionskasse im Rahmen eines Stellenwechsels.\n\n"
        "Wir bitten Sie, folgende Angaben zu übermitteln:\n"
        "  · Eintrittsdatum (TT. Monat JJJJ)\n"
        "  · BVG-Koordinationsabzug (CHF)\n"
        "  · Bestätigung der BVG-Pflicht\n\n"
        "Die Angaben dienen der Vorbereitung des Freizügigkeits-Transfers "
        "und der Eröffnung des Vorsorgekontos gemäss BVG."
    ),
    Actor.AVS: (
        "wir koordinieren im Auftrag des/der nachfolgend genannten Versicherten "
        "die Überprüfung des AHV-Beitragskontos im Rahmen eines Stellenwechsels.\n\n"
        "Wir bitten Sie, folgende Angaben zu übermitteln:\n"
        "  · Verfügbarkeit des Individuellen Kontos (IK-Auszug)\n"
        "  · Anzahl anrechenbarer Beitragsjahre\n"
        "  · Allfällige Beitragslücken (Anzahl Jahre)\n\n"
        "Die Angaben dienen der Vollständigkeitsprüfung des Vorsorgeprofils."
    ),
}


def _build_incoming_email(actor: Actor, case: dict) -> str:
    """Build simulated incoming HelveVista email HTML for this institution."""
    case_id    = case.get("case_id", "—")
    user_name  = case.get("user_name", "Versicherter")
    user_email = case.get("user_email", "")
    ctx        = case.get("structured_context", {})
    raw_sit    = ctx.get("user_summary") or case.get("situation", "—")
    situation  = raw_sit[:260] + ("…" if len(raw_sit) > 260 else "")

    requests_d = case.get("requests", {})
    sent_ts    = requests_d.get(actor.value, {}).get("sent_at")
    if sent_ts:
        sent_date     = time.strftime("%d. %B %Y", time.localtime(sent_ts))
        deadline_date = time.strftime("%d. %B %Y", time.localtime(sent_ts + 3 * 24 * 3600))
    else:
        sent_date     = time.strftime("%d. %B %Y")
        deadline_date = "3 Werktage ab Erhalt"

    actor_label  = ACTOR_LABELS[actor]
    subject      = f"{_ACTOR_EMAIL_SUBJECT[actor]} — Fall {case_id}"
    body_lines   = _ACTOR_EMAIL_BODY[actor].replace("\n", "<br>")
    user_display = user_name + (f" &lt;{user_email}&gt;" if user_email else "")

    return (
        f'<div class="hv-email-card">'
        f'<div class="hv-email-header-row">'
        f'<div>Von:&nbsp;&nbsp;&nbsp;<span>HelveVista &lt;koordination@helvevista.ch&gt;</span></div>'
        f'<div>An:&nbsp;&nbsp;&nbsp;&nbsp;<span>{actor_label}</span></div>'
        f'<div>Betreff: <span>{subject}</span></div>'
        f'<div>Datum:&nbsp;&nbsp;<span>{sent_date}</span></div>'
        f'<div style="margin-top:0.4rem; padding-top:0.4rem; border-top:1px solid #1A3048;">'
        f'Frist: <span style="color:#C9A84C; font-weight:600;">{deadline_date}</span></div>'
        f'</div>'
        f'<div class="hv-email-body">'
        f'<p>Sehr geehrte Damen und Herren,</p>'
        f'<p>{body_lines}</p>'
        f'<p><strong style="color:#C8D8E8;">Versicherter/Versicherte:</strong> {user_display}</p>'
        f'<p><strong style="color:#C8D8E8;">Situation:</strong> {situation}</p>'
        f'<p><strong style="color:#C8D8E8;">Fall-ID:</strong> '
        f'<span style="font-family:monospace; color:#C9A84C;">{case_id}</span></p>'
        f'<p style="margin-top:1rem; padding-top:0.8rem; border-top:1px solid #1A3048;">'
        f'Mit freundlichen Grüssen,<br>'
        f'<strong style="color:#C8D8E8;">HelveVista Koordinationsstelle</strong><br>'
        f'<span style="color:#4A7A9A; font-size:0.82rem;">koordination@helvevista.ch</span></p>'
        f'</div>'
        f'</div>'
    )


def _build_outgoing_email_preview(actor: Actor, case: dict, response: dict) -> str:
    """Build simulated outgoing institution response email HTML."""
    case_id     = case.get("case_id", "—")
    actor_label = ACTOR_LABELS[actor]
    actor_email = f"administration@{actor.value.lower().replace('_', '-')}.ch"
    subject     = f"Re: {_ACTOR_EMAIL_SUBJECT[actor]} — Fall {case_id}"
    today       = time.strftime("%d. %B %Y")
    user_name   = case.get("user_name", "den/die Versicherte/n")

    if actor == Actor.OLD_PK:
        chf   = response.get("freizuegigkeit_chf")
        chf_s = _fmt_chf(chf)
        rows  = (
            f"&nbsp;&nbsp;· Freizügigkeitsguthaben: <strong>{chf_s}</strong><br>"
            f"&nbsp;&nbsp;· Austrittsdatum: <strong>{_fmt_str(response.get('austrittsdatum'))}</strong><br>"
            f"&nbsp;&nbsp;· Status: <strong>{_fmt_str(response.get('status'))}</strong>"
        )
    elif actor == Actor.NEW_PK:
        koord   = response.get("bvg_koordinationsabzug")
        koord_s = _fmt_chf(koord)
        pflicht = "Ja" if response.get("bvg_pflicht") else "Nein"
        rows = (
            f"&nbsp;&nbsp;· Eintrittsdatum: <strong>{_fmt_str(response.get('eintrittsdatum'))}</strong><br>"
            f"&nbsp;&nbsp;· BVG-Koordinationsabzug: <strong>{koord_s}</strong><br>"
            f"&nbsp;&nbsp;· BVG-Pflicht: <strong>{pflicht}</strong>"
        )
    else:  # AVS
        _bj = response.get("beitragsjahre")
        _lk = response.get("luecken")
        rows = (
            f"&nbsp;&nbsp;· IK-Auszug: <strong>{_fmt_str(response.get('ik_auszug'))}</strong><br>"
            f"&nbsp;&nbsp;· Beitragsjahre: <strong>{_fmt_str(_bj) if _bj is None else _bj}</strong><br>"
            f"&nbsp;&nbsp;· Beitragslücken: <strong>{'nicht angegeben' if _lk is None else _lk}</strong>"
        )

    return (
        f'<div class="hv-email-card" style="border-left:3px solid #2E86AB;">'
        f'<div class="hv-email-header-row">'
        f'<div>Von:&nbsp;&nbsp;&nbsp;<span>{actor_label} &lt;{actor_email}&gt;</span></div>'
        f'<div>An:&nbsp;&nbsp;&nbsp;&nbsp;<span>HelveVista &lt;koordination@helvevista.ch&gt;</span></div>'
        f'<div>Betreff: <span>{subject}</span></div>'
        f'<div>Datum:&nbsp;&nbsp;<span>{today}</span></div>'
        f'</div>'
        f'<div class="hv-email-body">'
        f'<p>Sehr geehrte Koordinationsstelle,</p>'
        f'<p>wir bestätigen folgende Angaben für {user_name}:</p>'
        f'<p>{rows}</p>'
        f'<p>Diese Angaben wurden geprüft und sind rechtsverbindlich.<br>'
        f'Bei Rückfragen stehen wir Ihnen gerne zur Verfügung.</p>'
        f'<p>Mit freundlichen Grüssen,<br>'
        f'<strong style="color:#C8D8E8;">{actor_label}</strong></p>'
        f'</div>'
        f'</div>'
    )


def _inst_header(actor: Actor) -> None:
    """Render institution portal header: name + INSTITUTION badge."""
    col_title, col_badge = st.columns([4, 1])
    with col_title:
        st.markdown(
            f'<div class="hv-label" style="margin-bottom:0.15rem;">Institutionen-Portal</div>'
            f'<h2 style="margin-top:0;">{ACTOR_LABELS[actor]}</h2>',
            unsafe_allow_html=True,
        )
    with col_badge:
        st.markdown(
            '<div style="text-align:right; padding-top:1.5rem;">'
            '<span class="hv-inst-badge">INSTITUTION</span>'
            '</div>',
            unsafe_allow_html=True,
        )


def _inst_case_overview(case: dict) -> None:
    """Right column: case overview card with actor states + timeline."""
    with st.container(border=True):
        st.markdown(
            '<div class="hv-label" style="margin-bottom:0.6rem;">Fallübersicht</div>',
            unsafe_allow_html=True,
        )

        # Orchestrator state
        orch_state = case.get("orchestrator_state", "INIT")
        if "CLOSED_SUCCESS" in orch_state:
            orch_color = "#4CAF82"
        elif "ESCALATED" in orch_state or "ABORTED" in orch_state:
            orch_color = "#CF6679"
        elif "USER_VALIDATION" in orch_state:
            orch_color = "#C9A84C"
        else:
            orch_color = "#5A9ABE"
        st.markdown(
            f'<div style="margin-bottom:0.7rem;">'
            f'<span class="hv-meta-label">Prozess-Status</span>'
            f'<span style="color:{orch_color}; font-size:0.88rem; font-weight:500;">'
            f'{orch_state.replace("_", " ")}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        st.markdown(
            '<hr style="border-color:#1A3048; margin:0.4rem 0 0.6rem 0;">',
            unsafe_allow_html=True,
        )

        # Actor states
        st.markdown(
            '<span class="hv-meta-label" style="margin-bottom:0.5rem; display:block;">'
            'Beteiligte Institutionen</span>',
            unsafe_allow_html=True,
        )
        actor_states = case.get("actor_states", {})
        valid_state_values = {s.value for s in ActorState}
        for a in Actor:
            a_state_val = actor_states.get(a.value, ActorState.PENDING.value)
            if a_state_val in valid_state_values:
                a_state = ActorState(a_state_val)
            else:
                a_state = ActorState.PENDING
            _, label, badge_kind = STATE_DISPLAY.get(a_state, ("—", a_state_val, "pending"))
            st.markdown(
                f'<div style="display:flex; justify-content:space-between; '
                f'align-items:center; margin-bottom:0.35rem;">'
                f'<span style="color:#8AAEC8; font-size:0.8rem;">{ACTOR_LABELS[a]}</span>'
                f'<span class="hv-badge hv-badge-{badge_kind}" style="font-size:0.65rem;">'
                f'{label}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

        st.markdown(
            '<hr style="border-color:#1A3048; margin:0.5rem 0 0.6rem 0;">',
            unsafe_allow_html=True,
        )

        # Timeline
        st.markdown(
            '<span class="hv-meta-label" style="margin-bottom:0.5rem; display:block;">'
            'Zeitleiste</span>',
            unsafe_allow_html=True,
        )
        timeline: list[tuple[str, str]] = []

        created_at = case.get("created_at", "")
        if created_at:
            timeline.append((created_at[:16].replace("T", " "), "Fall eröffnet"))

        for av, req in case.get("requests", {}).items():
            ts = req.get("sent_at")
            if ts:
                ts_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
                alabel = ACTOR_LABELS.get(_actor_from_str(av), av)  # type: ignore[arg-type]
                timeline.append((ts_str, f"Anfrage gesendet — {alabel}"))

        for av, is_resp in case.get("institution_responded", {}).items():
            if is_resp:
                resp_date = case.get("institution_response_date", {}).get(av, "")
                if resp_date:
                    alabel = ACTOR_LABELS.get(_actor_from_str(av), av)  # type: ignore[arg-type]
                    timeline.append((resp_date[:16].replace("T", " "), f"Antwort erhalten — {alabel}"))

        if timeline:
            html = '<div class="hv-timeline">'
            for ts, label in timeline:
                html += (
                    f'<div class="hv-timeline-item">'
                    f'<div class="hv-timeline-ts">{ts}</div>'
                    f'<div class="hv-timeline-label">{label}</div>'
                    f'</div>'
                )
            html += '</div>'
            st.markdown(html, unsafe_allow_html=True)
        else:
            st.caption("Noch keine Ereignisse.")


def _render_person_summary_card(case: dict) -> None:
    """Two-column 'Angaben zur versicherten Person' info card."""
    ctx = case.get("structured_context", {})
    doc = case.get("extracted_doc_data", {})

    def _fhtml(label: str, value: str) -> str:
        return (
            f'<div style="margin-bottom:0.7rem;">'
            f'<div style="color:#C9A84C; font-size:0.62rem; letter-spacing:0.2em; '
            f'font-variant:small-caps; margin-bottom:0.15rem;">{label}</div>'
            f'<div style="color:#FFFFFF; font-size:0.88rem;">{value}</div>'
            f'</div>'
        )

    raw_sum   = ctx.get("user_summary", "") or ""
    situation = (raw_sum[:100] + "…") if len(raw_sum) > 100 else (raw_sum or "—")

    core_left = [
        ("NAME",      case.get("user_name", "—") or "—"),
        ("E-MAIL",    case.get("user_email", "—") or "—"),
        ("FALL-ID",   case.get("case_id",    "—") or "—"),
    ]
    core_right = [
        ("VERFAHREN", ctx.get("use_case", "STELLENWECHSEL")),
        ("SITUATION", situation),
    ]

    doc_rows: list[tuple[str, str]] = []
    if doc.get("ahv_nummer"):
        doc_rows.append(("AHV-NUMMER",               str(doc["ahv_nummer"])))
    if doc.get("pensionskasse"):
        doc_rows.append(("BISHERIGE PENSIONSKASSE",   str(doc["pensionskasse"])))
    if doc.get("freizuegigkeit_chf"):
        doc_rows.append(("FREIZÜGIGKEITSGUTHABEN CHF", str(doc["freizuegigkeit_chf"])))
    if doc.get("austrittsdatum"):
        doc_rows.append(("AUSTRITTSDATUM",            str(doc["austrittsdatum"])))
    if doc.get("eintrittsdatum"):
        doc_rows.append(("EINTRITTSDATUM",            str(doc["eintrittsdatum"])))
    if doc.get("email"):
        doc_rows.append(("E-MAIL INSTITUTION",        str(doc["email"])))
    if doc.get("telefon"):
        doc_rows.append(("TELEFON INSTITUTION",       str(doc["telefon"])))

    half = (len(doc_rows) + 1) // 2
    left  = core_left  + doc_rows[:half]
    right = core_right + doc_rows[half:]

    with st.container(border=True):
        st.markdown(
            '<div style="color:#C9A84C; font-size:0.68rem; letter-spacing:0.25em; '
            'margin-bottom:0.8rem;">ANGABEN ZUR VERSICHERTEN PERSON</div>',
            unsafe_allow_html=True,
        )
        col_a, col_b = st.columns(2)
        with col_a:
            for lbl, val in left:
                st.markdown(_fhtml(lbl, val), unsafe_allow_html=True)
        with col_b:
            for lbl, val in right:
                st.markdown(_fhtml(lbl, val), unsafe_allow_html=True)


def _inst_dashboard() -> None:
    """Institution dashboard — professional two-column layout with case overview."""

    # Institution selector
    inst_map: dict[str, Actor] = {
        "Alte Pensionskasse":  Actor.OLD_PK,
        "Neue Pensionskasse":  Actor.NEW_PK,
        "AHV-Ausgleichskasse": Actor.AVS,
    }
    chosen_label = st.selectbox(
        "Angemeldet als",
        list(inst_map.keys()),
        index=0,
        key="inst_selector",
    )
    actor: Actor = inst_map[chosen_label]
    st.session_state.inst_actor = actor

    _inst_header(actor)

    case = _load_case()

    # Two-column layout: left = pending requests / status, right = case overview
    col_left, col_right = st.columns([3, 2], gap="large")

    with col_left:
        st.markdown(
            '<div class="hv-label">Eingehende Anfragen</div>',
            unsafe_allow_html=True,
        )

        if not case:
            st.markdown(
                '<div class="hv-empty-state">'
                '<div class="icon">📭</div>'
                '<div class="text">Keine offenen Anfragen.<br>'
                'Sie werden per E-Mail benachrichtigt, sobald<br>ein Fall für Sie vorliegt.</div>'
                '</div>',
                unsafe_allow_html=True,
            )
        else:
            activated  = case.get("activated_actors", [])
            responded  = case.get("institution_responded", {})
            case_id    = case.get("case_id", "—")
            ctx        = case.get("structured_context", {})
            raw_sit    = ctx.get("user_summary") or case.get("situation", "—")
            situation  = raw_sit[:200] + ("…" if len(raw_sit) > 200 else "")
            user_name  = case.get("user_name", "Versicherter")
            user_email = case.get("user_email", "")
            use_case   = ctx.get("use_case", "STELLENWECHSEL").replace("_", " ").title()
            requests_d = case.get("requests", {})
            sent_at    = requests_d.get(actor.value, {}).get("sent_at")
            if sent_at:
                deadline_str = time.strftime("%d. %B %Y", time.localtime(sent_at + 3 * 24 * 3600))
            else:
                deadline_str = "3 Werktage ab Erhalt"

            if actor.value not in activated:
                st.markdown(
                    '<div class="hv-empty-state">'
                    '<div class="icon">📭</div>'
                    '<div class="text">Keine offenen Anfragen.<br>'
                    'Sie werden per E-Mail benachrichtigt.</div>'
                    '</div>',
                    unsafe_allow_html=True,
                )

            elif actor.value in activated:
                # Show green confirmation if already responded
                if responded.get(actor.value):
                    resp_date      = case.get("institution_response_date", {}).get(actor.value, "")
                    resp_date_disp = resp_date[:16].replace("T", " ") if resp_date else "—"
                    st.markdown(
                        f'<div style="background:#071A0E; border:1px solid #1A4C30; '
                        f'border-left:3px solid #4CAF82; border-radius:4px; '
                        f'padding:1.2rem 1.4rem; margin-bottom:0.8rem;">'
                        f'<div style="color:#4CAF82; font-weight:600; margin-bottom:0.4rem;">'
                        f'✓ Anfrage beantwortet</div>'
                        f'<div style="color:#80B898; font-size:0.85rem; line-height:1.6;">'
                        f'Ihre Antwort wurde am <strong>{resp_date_disp}</strong> übermittelt.<br>'
                        f'HelveVista hat Ihre Angaben verarbeitet. Vielen Dank.</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

                # Always show the pending request card so institution can respond
                with st.container(border=True):
                    # Header row
                    col_ch, col_cb = st.columns([3, 1])
                    with col_ch:
                        st.markdown(
                            '<span style="color:#FFFFFF; font-weight:600; font-size:0.95rem;">'
                            'Neue Anfrage von HelveVista</span>',
                            unsafe_allow_html=True,
                        )
                    with col_cb:
                        st.markdown(_badge("Offen", "waiting"), unsafe_allow_html=True)

                    st.markdown(
                        '<hr style="border-color:#1A3048; margin:0.6rem 0;">',
                        unsafe_allow_html=True,
                    )

                    # Metadata rows
                    email_suffix = f" · {user_email}" if user_email else ""
                    st.markdown(
                        f'<div class="hv-meta-row">'
                        f'<span class="hv-meta-label">Fall-ID</span>'
                        f'<span class="hv-case-id">{case_id}</span>'
                        f'</div>'
                        f'<div class="hv-meta-row">'
                        f'<span class="hv-meta-label">Versicherter</span>'
                        f'<span style="color:#C8D8E8;">{user_name}{email_suffix}</span>'
                        f'</div>'
                        f'<div class="hv-meta-row">'
                        f'<span class="hv-meta-label">Verfahren</span>'
                        f'<span style="color:#C8D8E8;">{use_case}</span>'
                        f'</div>'
                        f'<div class="hv-meta-row">'
                        f'<span class="hv-meta-label">Situation</span>'
                        f'<span style="color:#8AAEC8; font-size:0.84rem;">{situation}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

                    with st.expander("Angaben zur versicherten Person"):
                        _render_person_summary_card(case)

                    # Requested document + fields
                    req_label  = _ACTOR_REQUEST_LABEL[actor]
                    req_fields = _ACTOR_REQUEST_FIELDS[actor]
                    st.markdown(
                        f'<div class="hv-meta-row" style="margin-top:0.4rem;">'
                        f'<span class="hv-meta-label">Anfrage</span>'
                        f'<span style="color:#C9A84C; font-weight:500;">{req_label}</span>'
                        f'</div>'
                        f'<div style="color:#5A8AAA; font-size:0.78rem; margin-bottom:0.5rem;">'
                        f'{req_fields}</div>'
                        f'<div class="hv-meta-row">'
                        f'<span class="hv-meta-label">Frist</span>'
                        f'<span style="color:#C08040; font-weight:500;">{deadline_str}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

                    st.markdown(
                        "<div style='height:0.5rem'></div>",
                        unsafe_allow_html=True,
                    )
                    if st.button(
                        "Anfrage bearbeiten",
                        type="primary",
                        use_container_width=True,
                        key="inst_dash_open_btn",
                    ):
                        st.session_state.inst_view = "form"
                        st.rerun()

    with col_right:
        if case:
            _inst_case_overview(case)

    # ── Phase 2: institution sends clarification request to user ─────────────
    if case and actor.value in case.get("activated_actors", []):
        already_responded = case.get("institution_responded", {}).get(actor.value)
        pending_clarifs   = case.get("institution_clarification_requests", {}).get(
            actor.value, []
        )
        user_resps        = case.get("user_clarification_responses", {}).get(
            actor.value, []
        )

        st.markdown("---")
        st.markdown(
            '<div class="hv-label">Rückfrage an den Versicherten senden</div>',
            unsafe_allow_html=True,
        )

        # Show any already-sent clarification requests and their answers
        if pending_clarifs:
            for i, req in enumerate(pending_clarifs):
                with st.container(border=True):
                    ts_raw  = req.get("sent_at", "")
                    ts_disp = ts_raw[:16].replace("T", " ") if ts_raw else "—"
                    st.markdown(
                        f'<div style="color:#C9A84C; font-size:0.72rem; '
                        f'letter-spacing:0.12em; margin-bottom:0.3rem;">'
                        f'GESENDET {ts_disp}</div>'
                        f'<div style="color:#C8D8E8; font-size:0.88rem;">'
                        f'{req.get("text", "")}</div>',
                        unsafe_allow_html=True,
                    )
                    if i < len(user_resps):
                        ans = user_resps[i]
                        st.markdown(
                            f'<div style="margin-top:0.5rem; padding:0.5rem 0.8rem; '
                            f'background:#071A0E; border-left:2px solid #4CAF82; '
                            f'border-radius:2px; color:#80B898; font-size:0.84rem;">'
                            f'<span style="color:#4CAF82; font-size:0.68rem; '
                            f'letter-spacing:0.15em;">ANTWORT DES VERSICHERTEN</span><br>'
                            f'{ans.get("text", "")}</div>',
                            unsafe_allow_html=True,
                        )
                    else:
                        st.caption("Antwort des Versicherten ausstehend.")

        # Compose new clarification request
        new_clarif = st.text_area(
            "Neue Rückfrage",
            placeholder=(
                "Beispiel: Bitte bestätigen Sie das genaue Eintrittsdatum bei "
                "Ihrem neuen Arbeitgeber."
            ),
            height=100,
            key=f"inst_clarif_{actor.value}",
            label_visibility="visible",
        )
        if st.button(
            "Rückfrage senden",
            key=f"inst_clarif_send_{actor.value}",
            type="primary",
            disabled=not (new_clarif or "").strip(),
        ):
            c = _load_case()
            entry = {
                "text":    new_clarif.strip(),
                "sent_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            c.setdefault("institution_clarification_requests", {}).setdefault(
                actor.value, []
            ).append(entry)
            _save_case(c)
            st.success(
                "Rückfrage gespeichert. Der Versicherte wird in HelveVista "
                "aufgefordert zu antworten."
            )
            st.rerun()

    # ── Rückfragen section (full width, below) ────────────────────────────────
    if case:
        questions = case.get("follow_up_questions", {}).get(actor.value, [])
        if questions:
            st.markdown("---")
            st.markdown(
                '<div class="hv-label">Rückfragen des Versicherten</div>',
                unsafe_allow_html=True,
            )
            answers = case.get("follow_up_answers", {}).get(actor.value, [])
            for i, item in enumerate(questions):
                with st.container(border=True):
                    col_q, col_ts = st.columns([4, 1])
                    with col_q:
                        st.markdown(
                            f'<span style="color:#C9A84C; font-weight:600;">Frage {i + 1}:</span> '
                            f'{item.get("question", "—")}',
                            unsafe_allow_html=True,
                        )
                    with col_ts:
                        ts_raw = item.get("sent_at", "")
                        st.caption(ts_raw[:16].replace("T", " ") if ts_raw else "—")

                    existing_answer = answers[i]["answer"] if i < len(answers) else None
                    if existing_answer:
                        st.markdown(
                            f'<div style="margin-top:0.5rem; padding:0.6rem 0.8rem; '
                            f'background:#0A1E30; border-left:2px solid #2E86AB; '
                            f'border-radius:2px; font-size:0.85rem; color:#8AAEC8;">'
                            f'<span style="color:#2E86AB; font-weight:600; '
                            f'font-size:0.7rem; letter-spacing:0.15em;">IHRE ANTWORT</span><br>'
                            f'{existing_answer}</div>',
                            unsafe_allow_html=True,
                        )
                    else:
                        answer_text = st.text_area(
                            "Ihre Antwort",
                            placeholder="Schreiben Sie Ihre Antwort auf diese Frage…",
                            height=80,
                            key=f"fu_answer_{actor.value}_{i}",
                            label_visibility="visible",
                        )
                        if st.button(
                            "Antwort senden",
                            key=f"fu_send_{actor.value}_{i}",
                            type="primary",
                        ):
                            if answer_text.strip():
                                c = _load_case()
                                ans_list = c.setdefault("follow_up_answers", {}).setdefault(
                                    actor.value, []
                                )
                                while len(ans_list) < i:
                                    ans_list.append(None)
                                entry = {
                                    "answer":  answer_text.strip(),
                                    "sent_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                }
                                if len(ans_list) == i:
                                    ans_list.append(entry)
                                else:
                                    ans_list[i] = entry
                                _save_case(c)
                                st.success("Antwort gespeichert.")
                                st.rerun()
                            else:
                                st.warning("Bitte geben Sie Ihre Antwort ein.")


def _inst_form() -> None:
    """Institution response form — email on left, fields on right, preview below."""
    actor: Optional[Actor] = st.session_state.inst_actor
    if actor is None:
        st.session_state.inst_view = "dashboard"
        st.rerun()
        return

    case = _load_case()

    _inst_header(actor)
    st.markdown(
        '<div class="hv-label" style="margin-bottom:0.8rem;">Anfrage bearbeiten</div>',
        unsafe_allow_html=True,
    )

    # Case summary card — Angaben zur versicherten Person
    _render_person_summary_card(case)
    st.markdown("<div style='height:0.6rem'></div>", unsafe_allow_html=True)

    # Two-column layout: left = incoming email, right = response form
    col_email, col_form = st.columns([5, 4], gap="large")

    with col_email:
        st.markdown(
            '<div class="hv-label">Eingehende E-Mail von HelveVista</div>',
            unsafe_allow_html=True,
        )
        st.markdown(_build_incoming_email(actor, case), unsafe_allow_html=True)

    response: dict = {}

    with col_form:
        st.markdown(
            '<div class="hv-label">Ihre Antwort</div>',
            unsafe_allow_html=True,
        )
        with st.container(border=True):
            if actor == Actor.OLD_PK:
                response["freizuegigkeit_chf"] = st.number_input(
                    "Freizügigkeitsguthaben (CHF)",
                    min_value=0,
                    value=45_200,
                    step=100,
                    help="Gesamtes Freizügigkeitsguthaben per Austrittsdatum",
                )
                response["austrittsdatum"] = st.text_input(
                    "Austrittsdatum",
                    value="31. März 2025",
                    help="Format: TT. Monat JJJJ",
                )
                response["status"] = st.selectbox(
                    "Status",
                    ["Austritt bestätigt", "Austritt ausstehend", "Daten unvollständig"],
                    help="Aktueller Bearbeitungsstatus",
                )

            elif actor == Actor.NEW_PK:
                response["eintrittsdatum"] = st.text_input(
                    "Eintrittsdatum",
                    value="1. April 2025",
                    help="Format: TT. Monat JJJJ",
                )
                response["bvg_koordinationsabzug"] = st.number_input(
                    "BVG-Koordinationsabzug (CHF)",
                    min_value=0,
                    value=26_460,
                    step=100,
                    help="Jährlicher Koordinationsabzug gemäss BVG",
                )
                response["bvg_pflicht"] = st.checkbox(
                    "BVG-Pflicht bestätigt",
                    value=True,
                    help="Versicherter ist BVG-pflichtig ab Eintrittsdatum",
                )

            elif actor == Actor.AVS:
                response["ik_auszug"] = st.selectbox(
                    "IK-Auszug",
                    ["verfügbar", "nicht verfügbar", "in Bearbeitung"],
                    help="Verfügbarkeit des Individuellen Kontos",
                )
                response["beitragsjahre"] = st.number_input(
                    "Beitragsjahre",
                    min_value=0,
                    max_value=45,
                    value=12,
                    help="Anzahl anrechenbarer AHV-Beitragsjahre",
                )
                response["luecken"] = st.number_input(
                    "Lücken (Anzahl Jahre)",
                    min_value=0,
                    max_value=45,
                    value=0,
                    help="Anzahl Beitragslückenjahre",
                )

    # Outgoing email preview (full width, below)
    st.markdown("---")
    st.markdown(
        '<div class="hv-label">Vorschau Ihrer Antwort-E-Mail</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Diese E-Mail wird nach Ihrer Übermittlung an koordination@helvevista.ch gesendet:"
    )
    st.markdown(_build_outgoing_email_preview(actor, case, response), unsafe_allow_html=True)

    st.markdown("<div style='height:0.4rem'></div>", unsafe_allow_html=True)

    col_back, col_send = st.columns(2)
    with col_back:
        if st.button("Zurück", use_container_width=True):
            st.session_state.inst_view = "dashboard"
            st.rerun()
    with col_send:
        if st.button("Antwort übermitteln", type="primary", use_container_width=True):
            now_str = time.strftime("%Y-%m-%dT%H:%M:%S")
            c = _load_case()
            c.setdefault("institution_responses", {})[actor.value]     = response
            c.setdefault("institution_responded", {})[actor.value]     = True
            c.setdefault("institution_response_date", {})[actor.value] = now_str
            _save_case(c)
            st.session_state.inst_view = "done"
            st.rerun()


def _inst_done() -> None:
    """Confirmation screen after institution submits — full professional layout."""
    actor: Optional[Actor] = st.session_state.inst_actor
    name = ACTOR_LABELS.get(actor, "Institution") if actor else "Institution"

    _inst_header(actor or Actor.OLD_PK)

    # Large confirmation card
    st.markdown(
        """
        <div class="hv-confirm">
          <div class="icon" style="color:#4CAF82;">✓</div>
          <div class="title">Antwort erfolgreich übermittelt</div>
          <div class="sub">Ihre Angaben wurden sicher an HelveVista übertragen.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    case = _load_case()
    resp = case.get("institution_responses", {}).get(actor.value if actor else "", {})

    # Submitted data — clean summary card
    if resp:
        st.markdown(
            '<div class="hv-label" style="margin-top:0.5rem;">Übermittelte Angaben</div>',
            unsafe_allow_html=True,
        )
        label_map: dict[str, str] = {
            "freizuegigkeit_chf":     "Freizügigkeitsguthaben",
            "austrittsdatum":         "Austrittsdatum",
            "status":                 "Status",
            "eintrittsdatum":         "Eintrittsdatum",
            "bvg_koordinationsabzug": "BVG-Koordinationsabzug",
            "bvg_pflicht":            "BVG-Pflicht",
            "ik_auszug":              "IK-Auszug",
            "beitragsjahre":          "Beitragsjahre",
            "luecken":                "Beitragslücken",
        }
        with st.container(border=True):
            for k, v in resp.items():
                display_label = label_map.get(k, k.replace("_", " ").title())
                if isinstance(v, bool):
                    display_v = "Ja" if v else "Nein"
                elif isinstance(v, (int, float)) and "chf" in k.lower():
                    display_v = _fmt_chf(v)
                else:
                    display_v = str(v)
                st.markdown(
                    f'<div style="display:flex; justify-content:space-between; '
                    f'align-items:center; padding:0.35rem 0; border-bottom:1px solid #1A3048;">'
                    f'<span style="color:#5A7A9A; font-size:0.85rem;">{display_label}</span>'
                    f'<span style="color:#C8D8E8; font-weight:500;">{display_v}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

    # HelveVista notification info
    st.markdown("<div style='height:0.4rem'></div>", unsafe_allow_html=True)
    st.info(
        "HelveVista wird den Versicherten über Ihre Antwort informieren. "
        "Der Koordinationsprozess wird automatisch fortgesetzt."
    )

    # Simulated email confirmation card
    resp_date = case.get("institution_response_date", {}).get(
        actor.value if actor else "", ""
    )
    resp_date_disp = resp_date[:16].replace("T", " ") if resp_date else time.strftime("%Y-%m-%d %H:%M")
    case_id_disp   = case.get("case_id", "—")

    st.markdown(
        '<div class="hv-label" style="margin-top:1rem;">E-Mail-Bestätigung</div>',
        unsafe_allow_html=True,
    )
    st.caption("Eine Kopie Ihrer Antwort wurde an koordination@helvevista.ch archiviert:")
    st.markdown(
        f'<div class="hv-email-card" style="border-left:3px solid #4CAF82;">'
        f'<div class="hv-email-header-row">'
        f'<div>Von:&nbsp;&nbsp;&nbsp;<span>HelveVista &lt;koordination@helvevista.ch&gt;</span></div>'
        f'<div>An:&nbsp;&nbsp;&nbsp;&nbsp;<span>{name}</span></div>'
        f'<div>Betreff: <span>Empfangsbestätigung — Fall {case_id_disp}</span></div>'
        f'<div>Datum:&nbsp;&nbsp;<span>{resp_date_disp}</span></div>'
        f'</div>'
        f'<div class="hv-email-body">'
        f'<p>Sehr geehrte Damen und Herren,</p>'
        f'<p>wir bestätigen den Eingang Ihrer Antwort für den Fall '
        f'<span style="font-family:monospace; color:#C9A84C;">{case_id_disp}</span>. '
        f'Ihre Angaben wurden in das Koordinationssystem übernommen und werden '
        f'unveränderlich im Ereignisprotokoll gesichert.</p>'
        f'<p>Eine Kopie dieser Antwort wurde unter Referenz '
        f'<span style="font-family:monospace; color:#C9A84C;">{case_id_disp}</span> '
        f'archiviert.</p>'
        f'<p>Mit freundlichen Grüssen,<br>'
        f'<strong style="color:#C8D8E8;">HelveVista Koordinationsstelle</strong><br>'
        f'<span style="color:#4A7A9A; font-size:0.82rem;">koordination@helvevista.ch</span>'
        f'</p>'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)

    if st.button("Zurück zum Dashboard", type="primary", use_container_width=True):
        st.session_state.inst_view = "dashboard"
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# CONVERSATION TIMELINE (Phase 2 — async multi-turn)
# ══════════════════════════════════════════════════════════════════════════════

# Actor colour accents for timeline
_TIMELINE_ACTOR_STYLE: dict[str, tuple[str, str]] = {
    "system":       ("#2E4A5E", "#1A3048"),   # muted gray
    "helvevista":   ("#2E86AB", "#1A4060"),   # blue
    "institution":  ("#C9A84C", "#3A2800"),   # gold
    "versicherter": ("#4CAF82", "#0C2818"),   # green
}


def _render_conversation_timeline(case: dict) -> None:
    """
    Render the full chronological conversation thread for a case.

    Render the full chronological conversation thread for a case.
    Purely presentational — no state mutations.
    """
    events = []

    if not events:
        st.markdown(
            '<div class="hv-empty-state">'
            '<div class="text">Noch keine Kommunikation in diesem Fall.</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    for event in events:
        actor     = event.get("actor", "system")
        label     = event.get("label", "")
        detail    = event.get("detail", "")
        ts        = event.get("timestamp", "")
        ts_disp   = ts[:16].replace("T", " ") if ts else "—"
        dot_color, bg_color = _TIMELINE_ACTOR_STYLE.get(actor, ("#2E4A5E", "#1A3048"))

        # Build timeline item HTML
        detail_html = (
            f'<div style="margin-top:0.25rem; color:#8AAEC8; '
            f'font-size:0.82rem; line-height:1.6;">{detail}</div>'
            if detail else ""
        )

        st.markdown(
            f'<div style="position:relative; padding:0.5rem 0 0.5rem 1.4rem; '
            f'border-left:2px solid {dot_color}40; margin-bottom:0.1rem;">'
            f'<div style="position:absolute; left:-5px; top:0.65rem; '
            f'width:8px; height:8px; border-radius:50%; '
            f'background:{dot_color};"></div>'
            f'<div style="font-family:\'Courier New\',monospace; '
            f'font-size:0.65rem; color:#2E5A78; margin-bottom:0.1rem;">{ts_disp}</div>'
            f'<div style="font-size:0.84rem; color:#C8D8E8; font-weight:500;">{label}</div>'
            f'{detail_html}'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)


# ── Pending institution clarifications (user-facing action banner) ────────────

def _render_pending_clarifications(case: dict) -> bool:
    """
    If there are unanswered institution clarification requests, render
    an action-required section with response fields.

    Returns True if any pending clarifications were shown (so the caller
    can decide whether to suppress other UI sections).
    """
    pending = []
    if not pending:
        return False

    st.markdown("---")
    st.markdown(
        '<div class="hv-label" style="color:#C08040;">Handlung erforderlich</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        "Eine oder mehrere Institutionen haben eine Rückfrage gestellt. "
        "Bitte antworten Sie, damit der Prozess fortgesetzt werden kann."
    )

    for req in pending:
        av         = req["actor_value"]
        al         = req["actor_label"]
        req_text   = req.get("text", "")
        sent_at    = req.get("sent_at", "")
        ts_disp    = sent_at[:16].replace("T", " ") if sent_at else "—"

        with st.container(border=True):
            st.markdown(
                f'<div style="display:flex; justify-content:space-between; '
                f'align-items:baseline; margin-bottom:0.4rem;">'
                f'<span style="color:#C9A84C; font-weight:600; '
                f'font-size:0.88rem;">{al}</span>'
                f'<span style="color:#2E5A78; font-family:\'Courier New\',monospace; '
                f'font-size:0.68rem;">{ts_disp}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<div style="background:#0D1B2A; border-left:2px solid #C9A84C; '
                f'padding:0.6rem 0.9rem; border-radius:2px; '
                f'color:#C8D8E8; font-size:0.88rem; line-height:1.7; '
                f'margin-bottom:0.6rem;">'
                f'{req_text}'
                f'</div>',
                unsafe_allow_html=True,
            )

            response_key = f"clarif_resp_{av}_{sent_at}"
            response_text = st.text_area(
                "Ihre Antwort",
                placeholder="Schreiben Sie Ihre Antwort an die Institution…",
                height=100,
                key=response_key,
                label_visibility="visible",
            )

            if st.button(
                "Antwort senden",
                key=f"clarif_send_{av}_{sent_at}",
                type="primary",
                use_container_width=True,
                disabled=not (response_text or "").strip(),
            ):
                c = _load_case()
                resp_entry = {
                    "text":    response_text.strip(),
                    "sent_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }
                c.setdefault("user_clarification_responses", {}).setdefault(
                    av, []
                ).append(resp_entry)
                _save_case(c)
                st.success("Ihre Antwort wurde übermittelt.")
                st.rerun()

    return True


# ══════════════════════════════════════════════════════════════════════════════
# ONBOARDING — 4-step interactive introduction (shown once before login)
# ══════════════════════════════════════════════════════════════════════════════

def _show_onboarding() -> None:
    """Render the 4-step onboarding flow. Sets onboarding_done when complete."""

    step = st.session_state.onboarding_step

    # ── Centered container CSS ─────────────────────────────────────────────────
    st.markdown(
        """
        <style>
        .ob-wrap {
            max-width: 700px;
            margin: 0 auto;
            padding: 2rem 1rem 1rem 1rem;
        }
        .ob-icon-wrap {
            text-align: center;
            margin-bottom: 1.8rem;
        }
        .ob-title {
            text-align: center;
            color: #FFFFFF;
            font-size: 1.75rem;
            font-weight: 300;
            letter-spacing: 0.04em;
            margin-bottom: 0.5rem;
        }
        .ob-subtitle {
            text-align: center;
            color: #C9A84C;
            font-size: 0.85rem;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            margin-bottom: 1.8rem;
        }
        .ob-body {
            color: #8AAEC8;
            font-size: 0.95rem;
            line-height: 1.85;
            text-align: center;
            max-width: 560px;
            margin: 0 auto 2rem auto;
        }
        .ob-tl-item {
            display: flex;
            align-items: flex-start;
            gap: 1rem;
            padding: 0.75rem 0;
            border-bottom: 1px solid #1A3048;
        }
        .ob-tl-item:last-child { border-bottom: none; }
        .ob-tl-icon {
            flex-shrink: 0;
            width: 36px;
            height: 36px;
            background: #122033;
            border: 1px solid #1A3048;
            border-radius: 6px;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .ob-tl-num {
            flex-shrink: 0;
            width: 22px;
            height: 22px;
            background: #1A3048;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #C9A84C;
            font-size: 0.72rem;
            font-weight: 600;
            margin-top: 7px;
        }
        .ob-tl-text .ob-tl-title {
            color: #D0DCE8;
            font-size: 0.92rem;
            font-weight: 500;
            margin-bottom: 0.15rem;
        }
        .ob-tl-text .ob-tl-desc {
            color: #5A7A9A;
            font-size: 0.8rem;
            line-height: 1.5;
        }
        .ob-card {
            background: #122033;
            border: 1px solid #1A3048;
            border-radius: 8px;
            padding: 1.4rem 1.2rem;
            text-align: center;
            height: 100%;
        }
        .ob-card .ob-card-title {
            color: #D0DCE8;
            font-size: 0.9rem;
            font-weight: 500;
            margin: 0.8rem 0 0.5rem 0;
        }
        .ob-card .ob-card-body {
            color: #5A7A9A;
            font-size: 0.8rem;
            line-height: 1.6;
        }
        .ob-dots {
            display: flex;
            justify-content: center;
            gap: 0.5rem;
            margin-top: 1.5rem;
            margin-bottom: 0.5rem;
        }
        .ob-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #1A3048;
            display: inline-block;
        }
        .ob-dot-active { background: #C9A84C; }
        .ob-note {
            text-align: center;
            color: #3E5F7A;
            font-size: 0.72rem;
            letter-spacing: 0.02em;
            margin-top: 1.2rem;
            line-height: 1.6;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # ── SVG icon library ───────────────────────────────────────────────────────
    SVG_SHIELD = (
        '<svg width="64" height="64" viewBox="0 0 24 24" fill="none" '
        'xmlns="http://www.w3.org/2000/svg">'
        '<path d="M12 2L3 6v6c0 5.25 3.75 10.15 9 11.25C17.25 22.15 21 17.25 21 12V6L12 2z" '
        'stroke="#C9A84C" stroke-width="1.5" fill="none"/>'
        '<path d="M9 12l2 2 4-4" stroke="#C9A84C" stroke-width="1.5" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
        '</svg>'
    )
    SVG_ROCKET = (
        '<svg width="64" height="64" viewBox="0 0 24 24" fill="none" '
        'xmlns="http://www.w3.org/2000/svg">'
        '<path d="M12 2C12 2 6 6 6 13l3 1 1 3c3.5 1 7.5-1 9-6.5C20.5 5.5 12 2 12 2z" '
        'stroke="#C9A84C" stroke-width="1.5" fill="none"/>'
        '<circle cx="13.5" cy="9.5" r="1.5" stroke="#C9A84C" stroke-width="1.5"/>'
        '<path d="M6 13l-3 4 4-1M18 6l1-4-4 1" stroke="#C9A84C" stroke-width="1.5" '
        'stroke-linecap="round"/>'
        '</svg>'
    )

    # Small SVGs for timeline / cards
    def _svg_doc() -> str:
        return (
            '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" '
            'xmlns="http://www.w3.org/2000/svg">'
            '<path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6z" '
            'stroke="#C9A84C" stroke-width="1.5" fill="none"/>'
            '<path d="M14 2v6h6M16 13H8M16 17H8M10 9H8" stroke="#C9A84C" '
            'stroke-width="1.5" stroke-linecap="round"/>'
            '</svg>'
        )

    def _svg_search() -> str:
        return (
            '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" '
            'xmlns="http://www.w3.org/2000/svg">'
            '<circle cx="11" cy="11" r="7" stroke="#C9A84C" stroke-width="1.5"/>'
            '<path d="M21 21l-4.35-4.35" stroke="#C9A84C" stroke-width="1.5" '
            'stroke-linecap="round"/>'
            '</svg>'
        )

    def _svg_users() -> str:
        return (
            '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" '
            'xmlns="http://www.w3.org/2000/svg">'
            '<path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" stroke="#C9A84C" stroke-width="1.5"/>'
            '<circle cx="9" cy="7" r="4" stroke="#C9A84C" stroke-width="1.5"/>'
            '<path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75" '
            'stroke="#C9A84C" stroke-width="1.5"/>'
            '</svg>'
        )

    def _svg_mail() -> str:
        return (
            '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" '
            'xmlns="http://www.w3.org/2000/svg">'
            '<path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" '
            'stroke="#C9A84C" stroke-width="1.5" fill="none"/>'
            '<polyline points="22,6 12,13 2,6" stroke="#C9A84C" stroke-width="1.5"/>'
            '</svg>'
        )

    def _svg_chart() -> str:
        return (
            '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" '
            'xmlns="http://www.w3.org/2000/svg">'
            '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12" stroke="#C9A84C" '
            'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>'
            '</svg>'
        )

    def _svg_check() -> str:
        return (
            '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" '
            'xmlns="http://www.w3.org/2000/svg">'
            '<polyline points="20 6 9 17 4 12" stroke="#C9A84C" stroke-width="1.5" '
            'stroke-linecap="round" stroke-linejoin="round"/>'
            '</svg>'
        )

    def _svg_id() -> str:
        return (
            '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" '
            'xmlns="http://www.w3.org/2000/svg">'
            '<rect x="2" y="5" width="20" height="14" rx="2" stroke="#C9A84C" stroke-width="1.5"/>'
            '<circle cx="8" cy="12" r="2" stroke="#C9A84C" stroke-width="1.5"/>'
            '<path d="M13 10h5M13 14h3" stroke="#C9A84C" stroke-width="1.5" stroke-linecap="round"/>'
            '</svg>'
        )

    # ── Progress dots ──────────────────────────────────────────────────────────
    def _dots(current: int) -> str:
        dots = ""
        for i in range(4):
            cls = "ob-dot ob-dot-active" if i == current else "ob-dot"
            dots += f'<span class="{cls}"></span>'
        return f'<div class="ob-dots">{dots}</div>'

    # ── Logo (small, centered) ─────────────────────────────────────────────────
    st.markdown(
        '<div style="text-align:center; padding: 1.5rem 0 0.5rem 0; '
        'letter-spacing:0.12em;">'
        '<span style="color:#C9A84C; font-size:1.4rem; font-weight:700;">HELVE</span>'
        '<span style="color:#FFFFFF; font-size:1.4rem; font-weight:200;">VISTA</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    # ── Step content ───────────────────────────────────────────────────────────
    if step == 0:
        st.markdown(
            f'<div class="ob-icon-wrap">{SVG_SHIELD}</div>'
            '<div class="ob-title">Willkommen bei HelveVista</div>'
            '<div class="ob-subtitle">Ihr digitaler Koordinationsassistent für die berufliche Vorsorge</div>'
            '<div class="ob-body">'
            'Ein Stellenwechsel bedeutet mehr als nur ein neues Büro.<br>'
            'Ihre Pensionskasse muss umgezogen werden — und das erfordert<br>'
            'die Koordination mehrerer Institutionen gleichzeitig.<br><br>'
            'HelveVista übernimmt diese Koordination für Sie:<br>'
            'strukturiert, sicher und nachvollziehbar.'
            '</div>',
            unsafe_allow_html=True,
        )

    elif step == 1:
        st.markdown(
            '<div class="ob-title">So funktioniert HelveVista</div>'
            '<div class="ob-subtitle">Sechs Schritte — eine klare Struktur</div>',
            unsafe_allow_html=True,
        )
        timeline_items = [
            (_svg_doc(),    "1", "Situation beschreiben",
             "Schildern Sie Ihren Stellenwechsel in wenigen Sätzen."),
            (_svg_search(), "2", "Automatische Analyse",
             "HelveVista strukturiert Ihre Angaben und identifiziert Handlungsbedarf."),
            (_svg_users(),  "3", "Institutionen identifizieren",
             "Die beteiligten Pensionskassen und Ausgleichskassen werden ermittelt."),
            (_svg_mail(),   "4", "Koordination & Kommunikation",
             "HelveVista sendet Anfragen und verwaltet die Rückmeldungen."),
            (_svg_chart(),  "5", "Ergebnisse & Übersicht",
             "Alle Antworten werden zusammengefasst und verständlich dargestellt."),
            (_svg_check(),  "6", "Entscheid & Abschluss",
             "Sie bestätigen den Abschluss — HelveVista dokumentiert alles."),
        ]
        tl_html = '<div style="max-width:560px; margin:0 auto;">'
        for icon_svg, num, title, desc in timeline_items:
            tl_html += (
                f'<div class="ob-tl-item">'
                f'<div class="ob-tl-icon">{icon_svg}</div>'
                f'<div class="ob-tl-num">{num}</div>'
                f'<div class="ob-tl-text">'
                f'<div class="ob-tl-title">{title}</div>'
                f'<div class="ob-tl-desc">{desc}</div>'
                f'</div>'
                f'</div>'
            )
        tl_html += '</div>'
        st.markdown(tl_html, unsafe_allow_html=True)

    elif step == 2:
        st.markdown(
            '<div class="ob-title">Was Sie vorbereiten sollten</div>'
            '<div class="ob-subtitle">Drei Angaben — mehr braucht es nicht</div>',
            unsafe_allow_html=True,
        )
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown(
                f'<div class="ob-card">'
                f'<div style="display:flex;justify-content:center;">{_svg_doc()}</div>'
                f'<div class="ob-card-title">Ihre Situation</div>'
                f'<div class="ob-card-body">Beschreiben Sie kurz Ihren Stellenwechsel: '
                f'Wann, von welchem zu welchem Arbeitgeber.</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        with col2:
            st.markdown(
                f'<div class="ob-card">'
                f'<div style="display:flex;justify-content:center;">{_svg_id()}</div>'
                f'<div class="ob-card-title">Vorsorgeausweis (optional)</div>'
                f'<div class="ob-card-body">Falls vorhanden, laden Sie Ihren aktuellen '
                f'Vorsorgeausweis hoch. HelveVista extrahiert die relevanten Daten automatisch.</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        with col3:
            st.markdown(
                f'<div class="ob-card">'
                f'<div style="display:flex;justify-content:center;">{_svg_mail()}</div>'
                f'<div class="ob-card-title">E-Mail-Adressen (Live-Modus)</div>'
                f'<div class="ob-card-body">Im Live-Modus benötigen Sie die E-Mail-Adressen '
                f'Ihrer alten und neuen Pensionskasse.</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    elif step == 3:
        st.markdown(
            f'<div class="ob-icon-wrap">{SVG_ROCKET}</div>'
            '<div class="ob-title">Bereit?</div>'
            '<div class="ob-body">'
            'HelveVista führt Sie Schritt für Schritt durch den gesamten Prozess.<br>'
            'Sie behalten jederzeit die Kontrolle und müssen nichts bestätigen,<br>'
            'was Sie nicht verstehen.'
            '</div>',
            unsafe_allow_html=True,
        )

    # ── Progress dots ──────────────────────────────────────────────────────────
    st.markdown(_dots(step), unsafe_allow_html=True)
    st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)

    # ── Navigation buttons ─────────────────────────────────────────────────────
    if step == 3:
        # Final step — only "Jetzt starten"
        col_l, col_c, col_r = st.columns([1, 2, 1])
        with col_c:
            if st.button("Jetzt starten  →", type="primary", use_container_width=True):
                st.session_state.onboarding_done = True
                st.rerun()
        st.markdown(
            '<div class="ob-note">'
            'HelveVista ist ein Forschungsprototyp der ZHAW.<br>'
            'Alle Daten werden nur lokal gespeichert.'
            '</div>',
            unsafe_allow_html=True,
        )
    else:
        col_left, col_spacer, col_right = st.columns([2, 3, 2])
        with col_left:
            if step == 0:
                if st.button("Überspringen", type="secondary", use_container_width=True):
                    st.session_state.onboarding_done = True
                    st.rerun()
            else:
                if st.button("← Zurück", type="secondary", use_container_width=True):
                    st.session_state.onboarding_step = step - 1
                    st.rerun()
        with col_right:
            if st.button("Weiter  →", type="primary", use_container_width=True):
                st.session_state.onboarding_step = step + 1
                st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# CASE DASHBOARD — shows prior cases for logged-in users
# ══════════════════════════════════════════════════════════════════════════════

def _case_dashboard() -> None:
    """Show existing cases for the logged-in user."""
    try:
        from core.mongodb_client import list_cases, delete_case
        user_email = st.session_state.get("user_email", "")
        if not user_email:
            return
        cases = list_cases(user_email)
        if not cases:
            return

        st.markdown(
            """
<p style="color:#C9A84C; font-size:0.65rem; letter-spacing:0.3em;
          font-weight:500; text-transform:uppercase; margin-bottom:12px;">
  IHRE LAUFENDEN FÄLLE
</p>
""",
            unsafe_allow_html=True,
        )

        for c in cases:
            status = c.get("status", "EN_COURS")
            scenario = c.get("scenario", "stellenwechsel")
            updated = c.get("updated_at")
            case_id = c.get("case_id", "")
            data = c.get("data", {})
            situation = data.get("situation", "")
            preview = situation[:50] + "…" if situation else case_id

            status_colors = {
                "COMPLETED": "#6fcf97",
                "ESCALATED": "#eb5757",
                "EN_COURS": "#C9A84C",
            }
            status_color = status_colors.get(status, "#7A96B0")

            date_str = ""
            if updated:
                try:
                    date_str = updated.strftime("%d.%m.%Y %H:%M")
                except Exception:
                    date_str = str(updated)[:16]

            col_info, col_resume, col_delete = st.columns([5, 1, 1])

            with col_info:
                st.markdown(
                    f"""
<div style="background:#0d1f2d; border:1px solid #1a3a5c;
            border-radius:8px; padding:12px 16px; margin-bottom:8px;">
  <div style="display:flex; align-items:center; gap:12px; flex-wrap:wrap;">
    <span style="background:{status_color}22; color:{status_color};
                 border:1px solid {status_color}; border-radius:4px;
                 padding:2px 8px; font-size:0.7rem;
                 letter-spacing:0.05em;">{status}</span>
    <span style="color:#FFFFFF; font-size:0.88rem;
                 font-weight:500;">{scenario.upper()}</span>
    <span style="color:#3E5F7A; font-size:0.78rem;
                 margin-left:auto;">{date_str}</span>
  </div>
  <div style="color:#7A96B0; font-size:0.8rem;
              margin-top:6px;">{preview}</div>
</div>
""",
                    unsafe_allow_html=True,
                )

            with col_resume:
                if st.button("Fortsetzen", key=f"resume_{case_id}",
                             use_container_width=True):
                    st.session_state.case_id = case_id
                    st.session_state.case = data
                    _save_case(data)
                    st.session_state.vs_step = data.get("step", 1)
                    st.session_state.onboarding_done = True
                    st.rerun()

            with col_delete:
                if st.button("Löschen", key=f"delete_{case_id}",
                             use_container_width=True):
                    delete_case(case_id)
                    st.rerun()

        st.markdown(
            """
<hr style="border-color:#1a3a5c; margin:16px 0;"/>
<p style="color:#3E5F7A; font-size:0.78rem;
          text-align:center; margin-bottom:16px;">
  Oder starten Sie einen neuen Fall:
</p>
""",
            unsafe_allow_html=True,
        )

    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# SCENARIO SELECTION — landing page shown once before entering the main flow
# ══════════════════════════════════════════════════════════════════════════════

def _scenario_selection_page() -> None:
    """Full-page scenario picker. Sets selected_scenario and reruns on choice."""

    # ── Header ────────────────────────────────────────────────────────────────
    st.markdown(
        """
<div style="text-align:center; padding:3rem 0 0.75rem 0;">
  <span style="color:#C9A84C; font-size:3.5rem; font-weight:700;
               letter-spacing:0.12em;">Helve</span><span
        style="color:#FFFFFF; font-size:3.5rem; font-weight:200;
               letter-spacing:0.12em;">Vista</span>
</div>
<p style="text-align:center; color:#888; font-size:0.88rem;
          margin:0.25rem 0 1.25rem 0; letter-spacing:0.02em;">
  Koordination Ihrer Vorsorge — einfach, sicher, digital.
</p>
<hr style="border-color:#1A3048; margin:0 0 1.25rem 0;"/>
<p style="text-align:center; color:#3E5F7A; font-size:0.65rem;
          letter-spacing:0.3em; text-transform:uppercase;
          font-weight:500; margin-bottom:1.75rem;">
  Wählen Sie Ihr Anliegen
</p>
        """,
        unsafe_allow_html=True,
    )

    # ── Row 1 ─────────────────────────────────────────────────────────────────
    col1, col2 = st.columns(2)

    with col1:
        st.markdown(
            """
<div style="background:#0d1f2d; border:1.5px solid #C9A84C;
            border-radius:10px; padding:24px; min-height:180px;">
  <div style="margin-bottom:10px;"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#C9A84C" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/><line x1="12" y1="12" x2="12" y2="16"/><line x1="10" y1="14" x2="14" y2="14"/></svg></div>
  <p style="color:#FFFFFF; font-size:1.05rem; font-weight:600;
             letter-spacing:0.03em; margin:0 0 0.55rem 0;">Stellenwechsel</p>
  <p style="color:#7A96B0; font-size:0.84rem; line-height:1.65; margin:0;">
    Wechsel des Arbeitgebers mit korrekter Übertragung
    des BVG-Guthabens an die neue Pensionskasse.
  </p>
</div>
            """,
            unsafe_allow_html=True,
        )
        # Small top-margin spacer so the button sits flush under the card
        st.markdown("<div style='margin-top:6px;'></div>", unsafe_allow_html=True)
        if st.button(
            "Jetzt starten",
            key="btn_stellenwechsel",
            type="primary",
            use_container_width=True,
        ):
            st.session_state.selected_scenario = "stellenwechsel"
            st.rerun()

    with col2:
        st.markdown(
            """
<div style="background:#0d1f2d; border:1.5px solid #C9A84C;
            border-radius:10px; padding:24px; min-height:180px;">
  <div style="margin-bottom:10px;"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#C9A84C" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg></div>
  <p style="color:#FFFFFF; font-size:1.05rem; font-weight:600;
             letter-spacing:0.03em; margin:0 0 0.55rem 0;">Revue AVS</p>
  <p style="color:#7A96B0; font-size:0.84rem; line-height:1.65; margin:0;">
    Überprüfung Ihrer AHV-Situation — IK-Auszug,
    Beitragsjahre, Lücken und Rentenprojektion.
  </p>
</div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("<div style='margin-top:6px;'></div>", unsafe_allow_html=True)
        if st.button(
            "Jetzt starten",
            key="btn_revue_avs",
            type="primary",
            use_container_width=True,
        ):
            st.session_state.selected_scenario = "revue_avs"
            st.rerun()

    # ── Row 2 ─────────────────────────────────────────────────────────────────
    st.markdown("<div style='margin-top:14px;'></div>", unsafe_allow_html=True)
    col3, col4 = st.columns(2)

    with col3:
        st.markdown(
            """
<div style="background:#0d1f2d; border:1px solid #1a3a5c;
            border-radius:10px; padding:24px; min-height:180px; opacity:0.45;">
  <div style="margin-bottom:10px;"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#5A7A9A" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg></div>
  <p style="color:#FFFFFF; font-size:1.05rem; font-weight:600;
             letter-spacing:0.03em; margin:0 0 0.55rem 0;">Zivilstandsänderung</p>
  <p style="color:#7A96B0; font-size:0.84rem; line-height:1.65; margin:0 0 0.85rem 0;">
    Meldung einer Heirat, Scheidung oder eines
    Todesfalls an die zuständigen Vorsorgeeinrichtungen.
  </p>
  <span style="color:#5A7A9A; font-size:0.78rem; letter-spacing:0.1em;">
    In Entwicklung
  </span>
</div>
            """,
            unsafe_allow_html=True,
        )

    with col4:
        st.markdown(
            """
<div style="background:#0d1f2d; border:1px solid #1a3a5c;
            border-radius:10px; padding:24px; min-height:180px; opacity:0.45;">
  <div style="margin-bottom:10px;"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#5A7A9A" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg></div>
  <p style="color:#FFFFFF; font-size:1.05rem; font-weight:600;
             letter-spacing:0.03em; margin:0 0 0.55rem 0;">Pensionierung</p>
  <p style="color:#7A96B0; font-size:0.84rem; line-height:1.65; margin:0 0 0.85rem 0;">
    Koordination Ihrer Pensionierung —
    AHV, BVG und Säule 3a für einen optimalen Übertritt.
  </p>
  <span style="color:#5A7A9A; font-size:0.78rem; letter-spacing:0.1em;">
    In Entwicklung
  </span>
</div>
            """,
            unsafe_allow_html=True,
        )

    # ── Footer ────────────────────────────────────────────────────────────────
    st.markdown(
        """
<p style="text-align:center; color:#3E5F7A; font-size:0.68rem;
          letter-spacing:0.12em; margin-top:2.5rem;">
  HelveVista — Bachelorarbeit ZHAW 2026 |
  Supervisor: Prof. Dr. Alexandre De Spindler
</p>
        """,
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# ROUTER — dispatches to correct page/step based on session state
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    _inject_css()

    if not st.session_state.get("selected_scenario"):
        _scenario_selection_page()
        return

    if not st.session_state.onboarding_done:
        _show_onboarding()
        return

    if not st.session_state.logged_in:
        _page_login()
        return

    # Show case dashboard if user has prior cases (before entering the main flow)
    if (st.session_state.get("vs_step", 1) <= 1
            and st.session_state.get("user_email")):
        _case_dashboard()

    _render_sidebar()

    role = st.session_state.role

    if role == "versicherter":
        step = st.session_state.vs_step
        if   step == 1: _vs_step_1_situation()
        elif step == 2: _vs_step_2_analyse()
        elif step == 3: _vs_step_3_akteure()
        elif step == 4: _vs_step_4_koordination()
        elif step == 5: _vs_step_5_ergebnis()
        elif step == 6: _vs_step_6_entscheid()
        elif step == 7: _vs_step_final()

    elif role == "institution":
        view = st.session_state.inst_view
        if   view == "dashboard": _inst_dashboard()
        elif view == "form":      _inst_form()
        elif view == "done":      _inst_done()


main()

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
.hv-logo-lg .helve { color: #C9A84C; font-size: 3.2rem; font-weight: 700; }
.hv-logo-lg .vista { color: #FFFFFF;  font-size: 3.2rem; font-weight: 200; }
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
    try:
        with open(CASE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except IOError:
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
        "auto_sim_enabled": True,        # False → institutions must respond manually
        # Document extraction (Feature 2)
        "extracted_doc_data":  {},       # fields extracted from uploaded documents
        "_doc_upload_names":   [],       # track uploaded file names to detect new uploads
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
    if isinstance(v, (int, float)):
        return f"CHF {v:,.0f}".replace(",", "'")
    return str(v)


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
                value=st.session_state.get("auto_sim_enabled", True),
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
    The LLM acts as the institution and returns structured JSON.
    """
    import anthropic

    client = anthropic.Anthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY")
    )

    actor_name = ACTOR_LABELS[actor]

    system_prompt = (
        f"Du bist {actor_name}, eine Schweizer Vorsorgeeinrichtung. "
        f"Beantworte die Anfrage von HelveVista professionell und realistisch.\n\n"
        f"Kontext: {json.dumps(context, ensure_ascii=False)}\n\n"
        f"Antworte NUR als JSON mit diesen Feldern je nach Institution:\n"
        f"- OLD_PK: freizuegigkeit_chf (int), austrittsdatum (str), status (str)\n"
        f"- NEW_PK: eintrittsdatum (str), bvg_koordinationsabzug (int), bvg_pflicht (bool)\n"
        f"- AVS: ik_auszug (str), beitragsjahre (int), luecken (int)\n\n"
        f"Verwende realistische Schweizer Werte. Nur JSON, kein Text davor/danach."
    )

    try:
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=256,
            system=system_prompt,
            messages=[{"role": "user", "content": "Bitte antworte auf die HelveVista-Anfrage."}],
        )
        raw = msg.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
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
# DOCUMENT EXTRACTION (Feature 2)
# ══════════════════════════════════════════════════════════════════════════════

def _extract_doc_info(uploaded_files: list) -> dict:
    """
    Extract pension/contact information from uploaded documents via Claude API.

    Supports PDF (text extraction via pypdf if available, else skipped) and
    images (PNG/JPG — sent as base64 vision content).

    Returns a dict of extracted fields, or {} if nothing could be extracted.
    """
    import base64
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    content_parts: list[dict] = []

    for f in uploaded_files:
        file_bytes = f.read()
        file_ext   = f.name.lower().rsplit(".", 1)[-1]

        if file_ext == "pdf":
            # Try pypdf text extraction first
            text_extracted = ""
            try:
                import io
                import pypdf  # type: ignore[import]
                reader = pypdf.PdfReader(io.BytesIO(file_bytes))
                text_extracted = "\n".join(
                    page.extract_text() or "" for page in reader.pages
                )
            except Exception:
                pass

            if text_extracted.strip():
                content_parts.append({
                    "type": "text",
                    "text": f"Dokument '{f.name}':\n{text_extracted[:4000]}",
                })
            else:
                # pypdf unavailable or empty — inform model
                content_parts.append({
                    "type": "text",
                    "text": (
                        f"[PDF '{f.name}' konnte nicht als Text extrahiert werden. "
                        "Bitte installieren Sie pypdf für bessere PDF-Unterstützung.]"
                    ),
                })
        else:
            # Image — send as base64 vision block
            media_map = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}
            media_type = media_map.get(file_ext, "image/png")
            b64 = base64.b64encode(file_bytes).decode()
            content_parts.append({
                "type": "image",
                "source": {
                    "type":       "base64",
                    "media_type": media_type,
                    "data":       b64,
                },
            })

    if not content_parts:
        return {}

    content_parts.append({
        "type": "text",
        "text": "Extrahiere die Vorsorge-Informationen aus diesem Dokument.",
    })

    system_prompt = (
        "Du bist ein Vorsorge-Datenextraktor. Extrahiere aus dem Dokument "
        "ausschliesslich folgende Informationen falls vorhanden:\n"
        "- Name der versicherten Person\n"
        "- AHV-Nummer\n"
        "- Pensionskasse Name und Adresse\n"
        "- Freizügigkeitsguthaben CHF\n"
        "- Austrittsdatum / Eintrittsdatum\n"
        "- E-Mail oder Telefon der Institution\n"
        "Antworte nur in JSON. Fehlende Felder weglassen."
    )

    try:
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=512,
            system=system_prompt,
            messages=[{"role": "user", "content": content_parts}],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except Exception:
        return {}


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

    raw = st.text_area(
        "Ihre Situation",
        value=st.session_state.raw_input,
        placeholder=(
            "Beispiel: Ich wechsle meinen Job per 1. April 2025 von der Müller AG Zürich "
            "zur Novartis Basel. Was muss ich bezüglich meiner Pensionskasse und "
            "meinem AHV-Konto tun?"
        ),
        height=160,
        label_visibility="collapsed",
    )

    if not _use_llm():
        st.caption(
            "Demo-Modus — ANTHROPIC_API_KEY nicht gesetzt. "
            "Die Analyse wird mit Standardwerten simuliert."
        )

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
                if extracted:
                    st.session_state.extracted_doc_data = extracted
                    # Pre-fill situation text area if still empty
                    if not st.session_state.raw_input.strip():
                        _label_map = {
                            "name":               "Name",
                            "ahv_nummer":         "AHV-Nummer",
                            "pensionskasse":      "Pensionskasse",
                            "freizuegigkeit_chf": "Freizügigkeitsguthaben (CHF)",
                            "austrittsdatum":     "Austrittsdatum",
                            "eintrittsdatum":     "Eintrittsdatum",
                            "email":              "E-Mail Institution",
                            "telefon":            "Telefon Institution",
                        }
                        lines = [
                            f"{_label_map.get(k, k.replace('_', ' ').title())}: {v}"
                            for k, v in extracted.items()
                        ]
                        st.session_state.raw_input = "\n".join(lines)
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

    st.markdown("<div style='height:0.4rem'></div>", unsafe_allow_html=True)

    if st.button("Weiter", type="primary", use_container_width=True):
        if not raw.strip():
            st.warning("Bitte beschreiben Sie zuerst Ihre Situation.")
        else:
            st.session_state.raw_input = raw.strip()
            case = st.session_state.case
            case["situation"] = raw.strip()
            _save_case(case)
            _vs_go(2)
            st.rerun()


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
        case = st.session_state.case
        case["structured_context"] = {
            k: v
            for k, v in ctx.items()
            if k != "actors_enum"
        }
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
    st.markdown("## Beteiligte Institutionen")
    st.markdown(
        "HelveVista hat folgende Institutionen für Ihren Fall identifiziert. "
        "Alte und neue Pensionskasse sind für den Stellenwechsel obligatorisch."
    )

    ctx       = st.session_state.structured_ctx
    suggested = set(ctx.get("actors_enum", [Actor.OLD_PK, Actor.NEW_PK]))

    st.markdown("<div style='height:0.4rem'></div>", unsafe_allow_html=True)

    selected: dict[Actor, bool] = {}
    for actor in Actor:
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

    auto_sim_enabled = st.session_state.get("auto_sim_enabled", True)

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

        st.info(
            "Live-Modus aktiv. Bitte öffnen Sie das Institutionen-Portal "
            "in einem zweiten Tab und beantworten Sie die Anfragen manuell."
        )
        # Poll case_state.json for manual responses every 2 seconds
        all_responded = all(
            manual_case.get("institution_responded", {}).get(a.value, False)
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

    # ── Phase 2: show pending institution clarification requests first ─────────
    _render_pending_clarifications(case)

    # LLM-generated case summary (once)
    if st.session_state.llm_summary is None and _use_llm():
        with st.spinner("Zusammenfassung wird erstellt…"):
            from llm.structurer import generate_case_summary  # noqa: PLC0415
            st.session_state.llm_summary = generate_case_summary(orch._build_summary())

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
        resp    = inst_resp.get(actor.value) or DEMO_RESPONSES.get(actor, {})

        with st.container(border=True):
            col_h, col_b = st.columns([3, 1])
            with col_h:
                st.markdown(f"**{name}**")
            with col_b:
                st.markdown(_badge(label, badge_kind), unsafe_allow_html=True)

            if state == ActorState.COMPLETED and resp:
                st.markdown("<div style='height:0.3rem'></div>", unsafe_allow_html=True)

                if actor == Actor.OLD_PK:
                    chf = resp.get("freizuegigkeit_chf")
                    st.markdown(
                        f"Freizügigkeitsguthaben: **{_fmt_chf(chf) if chf is not None else '—'}**"
                    )
                    st.markdown(f"Austrittsdatum: **{resp.get('austrittsdatum', '—')}**")
                    st.markdown(f"Status: **{resp.get('status', '—')}**")

                elif actor == Actor.NEW_PK:
                    st.markdown(f"Eintrittsdatum: **{resp.get('eintrittsdatum', '—')}**")
                    koord = resp.get("bvg_koordinationsabzug")
                    st.markdown(
                        f"BVG-Koordinationsabzug: **{_fmt_chf(koord) if koord is not None else '—'}**"
                    )
                    pflicht = "Ja" if resp.get("bvg_pflicht") else "Nein"
                    st.markdown(f"BVG-Pflicht: **{pflicht}**")

                elif actor == Actor.AVS:
                    st.markdown(f"IK-Auszug: **{resp.get('ik_auszug', '—')}**")
                    st.markdown(f"Beitragsjahre: **{resp.get('beitragsjahre', '—')}**")
                    luecken = resp.get("luecken", 0)
                    luecken_label = "keine" if luecken == 0 else str(luecken)
                    st.markdown(f"Lücken: **{luecken_label}**")

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
                chf     = resp.get("freizuegigkeit_chf", "—")
                chf_fmt = _fmt_chf(chf) if isinstance(chf, (int, float)) else str(chf)
                explanation = (
                    f"Ihre alte Pensionskasse hat Ihr Freizügigkeitsguthaben von "
                    f"**{chf_fmt}** bestätigt. "
                    f"Dieses Guthaben wird automatisch auf Ihre neue Pensionskasse "
                    f"übertragen. Sie müssen nichts weiter unternehmen."
                )
                doc_name = "Freizügigkeitsabrechnung"

            elif actor == Actor.NEW_PK:
                datum     = resp.get("eintrittsdatum", "—")
                koord     = resp.get("bvg_koordinationsabzug", "—")
                koord_fmt = _fmt_chf(koord) if isinstance(koord, (int, float)) else str(koord)
                explanation = (
                    f"Ihre neue Pensionskasse hat Ihren Eintritt per **{datum}** "
                    f"bestätigt. Der BVG-Koordinationsabzug beträgt **{koord_fmt}**. "
                    f"Bewahren Sie die Eingangsbestätigung für Ihre Unterlagen auf."
                )
                doc_name = "Eingangsbestätigung"

            else:  # AVS
                jahre   = resp.get("beitragsjahre", "—")
                luecken = resp.get("luecken", 0)
                luecken_text = "ohne Lücken" if luecken == 0 else f"mit {luecken} Lückenjahr(en)"
                explanation = (
                    f"Die AHV-Ausgleichskasse hat Ihren IK-Auszug bereitgestellt. "
                    f"Sie haben **{jahre}** Beitragsjahre {luecken_text}. "
                    f"Dieser Auszug ist wichtig für Ihre spätere Rentenberechnung."
                )
                doc_name = "IK-Auszug"

            st.markdown(
                f'<div class="hv-label" style="margin-top:0.8rem;">{name}</div>',
                unsafe_allow_html=True,
            )
            st.info(explanation)

            req_already_sent  = actor.value in follow_up_reqs
            ques_already_sent = bool(follow_up_ques.get(actor.value))

            col_a, col_b = st.columns(2)

            with col_a:
                if req_already_sent:
                    st.markdown(
                        _badge("✓ Bereits gesendet", "completed"),
                        unsafe_allow_html=True,
                    )
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
                        disabled=req_already_sent,
                    ):
                        c = _load_case()
                        c.setdefault("follow_up_requests", {})[actor.value] = {
                            "text":    edited_text,
                            "sent_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        }
                        _save_case(c)
                        st.success("Anfrage wurde gespeichert.")
                        st.rerun()

            with col_b:
                if ques_already_sent:
                    st.markdown(
                        _badge("✓ Bereits gesendet", "completed"),
                        unsafe_allow_html=True,
                    )
                with st.expander(f"Rückfrage stellen"):
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
                            c.setdefault("follow_up_questions", {}).setdefault(
                                actor.value, []
                            ).append({
                                "question": question.strip(),
                                "sent_at":  time.strftime("%Y-%m-%dT%H:%M:%S"),
                            })
                            _save_case(c)
                            st.success("Rückfrage wurde gespeichert.")
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
    """Call Claude API with case context. Falls back to demo answer if no key."""
    import anthropic

    case_json = json.dumps(
        {
            "structured_context":    case.get("structured_context", {}),
            "institution_responses": case.get("institution_responses", {}),
            "final_decision":        case.get("final_decision"),
            "user_name":             case.get("user_name", ""),
            "actor_states":          case.get("actor_states", {}),
        },
        ensure_ascii=False,
        indent=2,
    )
    system_prompt = (
        "Du bist HelveVista. Beantworte NUR Fragen basierend auf diesen "
        f"konkreten Falldaten: {case_json}. "
        "Gib präzise, kurze Antworten (max 2 Sätze). "
        "Erfinde keine Zahlen oder Fakten die nicht in den Falldaten stehen. "
        "Wenn die Frage nicht durch die Falldaten beantwortet werden kann, "
        "antworte: 'AUSSERHALB_DES_FALLS: Diese Frage geht über Ihren Fall hinaus. "
        "Bitte kontaktieren Sie die zuständige Institution direkt.'"
    )
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

    freizuegigkeit_chf    = old_pk.get("freizuegigkeit_chf", "—")
    freizuegigkeit_fmt    = _fmt_chf(freizuegigkeit_chf) if isinstance(freizuegigkeit_chf, (int, float)) else str(freizuegigkeit_chf)
    bvg_koordinationsabzug = new_pk.get("bvg_koordinationsabzug", "—")
    koord_fmt             = _fmt_chf(bvg_koordinationsabzug) if isinstance(bvg_koordinationsabzug, (int, float)) else str(bvg_koordinationsabzug)
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
        chf   = response.get("freizuegigkeit_chf", "—")
        chf_s = _fmt_chf(chf) if isinstance(chf, (int, float)) else str(chf)
        rows  = (
            f"&nbsp;&nbsp;· Freizügigkeitsguthaben: <strong>{chf_s}</strong><br>"
            f"&nbsp;&nbsp;· Austrittsdatum: <strong>{response.get('austrittsdatum', '—')}</strong><br>"
            f"&nbsp;&nbsp;· Status: <strong>{response.get('status', '—')}</strong>"
        )
    elif actor == Actor.NEW_PK:
        koord   = response.get("bvg_koordinationsabzug", "—")
        koord_s = _fmt_chf(koord) if isinstance(koord, (int, float)) else str(koord)
        pflicht = "Ja" if response.get("bvg_pflicht") else "Nein"
        rows = (
            f"&nbsp;&nbsp;· Eintrittsdatum: <strong>{response.get('eintrittsdatum', '—')}</strong><br>"
            f"&nbsp;&nbsp;· BVG-Koordinationsabzug: <strong>{koord_s}</strong><br>"
            f"&nbsp;&nbsp;· BVG-Pflicht: <strong>{pflicht}</strong>"
        )
    else:  # AVS
        rows = (
            f"&nbsp;&nbsp;· IK-Auszug: <strong>{response.get('ik_auszug', '—')}</strong><br>"
            f"&nbsp;&nbsp;· Beitragsjahre: <strong>{response.get('beitragsjahre', '—')}</strong><br>"
            f"&nbsp;&nbsp;· Beitragslücken: <strong>{response.get('luecken', 0)}</strong>"
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
# ROUTER — dispatches to correct page/step based on session state
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    _inject_css()

    if not st.session_state.logged_in:
        _page_login()
        return

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

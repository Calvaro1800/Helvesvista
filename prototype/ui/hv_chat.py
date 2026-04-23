"""
ui/hv_chat.py
-------------
Persistent floating chat assistant for HelveVista 2.0.
inject() is called at the top of main() to render the FAB button and CSS.
render_panel() is called at the bottom of main() when chat_open=True.
"""
from __future__ import annotations
import os
import streamlit as st
import anthropic
from ui.hv_styles import HV_DARK, HV_CARD, HV_BORDER, HV_GOLD

MODEL = "claude-sonnet-4-20250514"

_OPENING_MSG = (
    "Guten Tag! Ich bin HelveVista, Ihr persönlicher Vorsorge-Assistent. "
    "Wie kann ich Ihnen helfen?"
)

# Options A, B, C, D embed their own chat — the floating chat is suppressed there.
_OWN_CHAT_OPTIONS = {"A", "B", "C", "D"}


def build_chat_context(
    scenario: str | None,
    option: str | None,
    vs_step: int,
    profile: dict,
    actor_states: dict,
) -> dict:
    """Return a context dict injected into every chat system prompt."""
    return {
        "scenario":     scenario or "—",
        "option":       option or "—",
        "vs_step":      vs_step,
        "vorname":      profile.get("vorname", "—"),
        "anstellung":   profile.get("anstellung", "—"),
        "actor_states": actor_states or {},
    }


def _system_prompt(ctx: dict) -> str:
    return (
        "Du bist HelveVista, ein Vorsorge-Assistent für das Schweizer 3-Säulen-System. "
        "Du eduzierts und verbindest — du rechnest niemals Beträge aus. "
        "Antworte immer auf Deutsch, präzise und freundlich.\n\n"
        f"Aktueller Kontext:\n"
        f"- Szenario: {ctx['scenario']}\n"
        f"- Option: {ctx['option']}\n"
        f"- Schritt (falls Option B aktiv): {ctx['vs_step']}\n"
        f"- Nutzer: {ctx['vorname']}, {ctx['anstellung']}\n"
        f"- Akteure: {ctx['actor_states']}\n"
    )


def inject() -> None:
    """
    Inject the floating chat FAB button and CSS.
    Must be called at the very top of main(), before any page content.
    Returns early (no-op) on pages with own embedded chat (options A, C, D),
    ensuring chat_open is False so render_panel() is also suppressed.
    When chat_open=True, call render_panel() at the bottom of main().
    """
    current_option = st.session_state.get("selected_option")

    # Change 6: Clear history whenever selected_option changes.
    # Runs before the early return so transitions TO own-chat options are tracked.
    if "_prev_chat_option" not in st.session_state:
        st.session_state["_prev_chat_option"] = current_option
    elif st.session_state["_prev_chat_option"] != current_option:
        st.session_state["chat_messages_global"] = []
        st.session_state["_prev_chat_option"] = current_option

    # Suppress floating chat when no option is selected (picker page) or option
    # has its own embedded chat.
    if current_option is None or current_option in _OWN_CHAT_OPTIONS:
        st.session_state["chat_open"] = False
        return

    # Initialise session state
    if "chat_messages_global" not in st.session_state:
        st.session_state.chat_messages_global = []
    if "chat_open" not in st.session_state:
        st.session_state.chat_open = False
    if "chat_input_cycle" not in st.session_state:
        st.session_state.chat_input_cycle = 0

    # Change 2: Auto-open once per page (scenario + option combination).
    scenario = st.session_state.get("selected_scenario")
    if scenario and st.session_state.get("logged_in"):
        page_key = f"_chat_auto_opened_{scenario}_{current_option or 'picker'}"
        if not st.session_state.get(page_key):
            st.session_state.chat_open = True
            st.session_state[page_key] = True

    # Change 1: CSS — circular gold FAB (40 px) + fixed 320×400 chat window.
    # FAB is targeted via aria-label (Streamlit sets aria-label = button label text).
    # Chat window is targeted via a sentinel class injected at render time.
    st.markdown(
        f"""
<style>
/* ── Circular FAB toggle button ─────────────────────── */
div[data-testid="stVerticalBlock"]:has(button[aria-label="💬"]) {{
    position: fixed !important;
    bottom: 22px !important;
    right: 22px !important;
    z-index: 9999 !important;
    width: auto !important;
}}
button[aria-label="💬"] {{
    background: #C9A84C !important;
    color: {HV_DARK} !important;
    border-radius: 50% !important;
    width: 40px !important;
    height: 40px !important;
    min-height: 40px !important;
    padding: 0 !important;
    border: none !important;
    box-shadow: 0 4px 16px rgba(0,0,0,0.4) !important;
    font-size: 1.25rem !important;
    line-height: 1 !important;
}}

/* ── Fixed 320×400 chat window ──────────────────────── */
div[data-testid="stVerticalBlock"]:has(.hv-chat-panel-marker) {{
    position: fixed !important;
    bottom: 80px !important;
    right: 22px !important;
    width: 320px !important;
    max-height: 400px !important;
    z-index: 9998 !important;
    background: {HV_CARD} !important;
    border: 1px solid {HV_BORDER} !important;
    border-radius: 12px !important;
    padding: 16px !important;
    overflow-y: auto !important;
    box-shadow: 0 8px 32px rgba(0,0,0,0.5) !important;
    box-sizing: border-box !important;
}}
</style>
        """,
        unsafe_allow_html=True,
    )

    if not st.session_state.chat_open:
        if st.button("💬", key="chat-fab-btn"):
            st.session_state.chat_open = True
            st.rerun()


def render_panel() -> None:
    """
    Render the 320×400 floating chat window.
    Call at the bottom of main() when chat_open=True.
    """
    if not st.session_state.chat_messages_global:
        st.session_state.chat_messages_global.append(
            {"role": "assistant", "content": _OPENING_MSG}
        )

    with st.container():
        # Sentinel that lets CSS position this container as the chat window.
        st.markdown(
            '<span class="hv-chat-panel-marker"></span>',
            unsafe_allow_html=True,
        )

        # Header row: title + X close button
        col1, col2 = st.columns([5, 1])
        with col1:
            st.markdown(
                f'<p style="color:{HV_GOLD};font-weight:600;font-size:.9rem;margin:0;">'
                f'💬 HelveVista Chat</p>',
                unsafe_allow_html=True,
            )
        with col2:
            if st.button("✕", key="chat-close-btn"):
                st.session_state.chat_open = False
                st.rerun()

        # Message history (last 12 messages)
        for msg in st.session_state.chat_messages_global[-12:]:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"], unsafe_allow_html=True)

        # Change 4: Key cycling clears the input field after each submission.
        input_cycle = st.session_state.get("chat_input_cycle", 0)
        user_input = st.chat_input(
            "Ihre Frage…",
            key=f"chat_global_input_{input_cycle}",
        )

    if user_input:
        st.session_state.chat_messages_global.append(
            {"role": "user", "content": user_input}
        )
        st.session_state.chat_input_cycle = input_cycle + 1

        ctx = build_chat_context(
            scenario=st.session_state.get("selected_scenario"),
            option=st.session_state.get("selected_option"),
            vs_step=st.session_state.get("vs_step", 1),
            profile=st.session_state.get("profile_data", {}),
            actor_states=st.session_state.get("case", {}).get("actor_states", {}),
        )
        # Change 3: Spinner while the LLM processes.
        with st.spinner("HelveVista tippt…"):
            answer = _llm_answer(user_input, ctx)

        st.session_state.chat_messages_global.append(
            {"role": "assistant", "content": answer}
        )
        st.rerun()


def _llm_answer(question: str, ctx: dict) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return "LLM nicht verfügbar (ANTHROPIC_API_KEY fehlt)."
    try:
        client = anthropic.Anthropic(api_key=api_key)
        history = st.session_state.chat_messages_global[-10:]
        messages = [{"role": m["role"], "content": m["content"]} for m in history]
        messages.append({"role": "user", "content": question})
        resp = client.messages.create(
            model=MODEL,
            max_tokens=512,
            system=_system_prompt(ctx),
            messages=messages,
        )
        return resp.content[0].text.strip()
    except Exception as e:
        return f"Fehler beim LLM-Aufruf: {e}"

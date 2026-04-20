"""
ui/hv_chat.py
-------------
Persistent floating chat assistant for HelveVista 2.0.
inject() is called at the top of main() to render the panel CSS and toggle.
The chat input is rendered at the bottom of main() when chat_open=True.
"""
from __future__ import annotations
import os
import streamlit as st
import anthropic
from ui.hv_styles import HV_DARK, HV_CARD, HV_BORDER, HV_GOLD, HV_MUTED, HV_TEXT

MODEL = "claude-sonnet-4-20250514"

_OPENING_MSG = (
    "Guten Tag! Ich bin HelveVista, Ihr persönlicher Vorsorge-Assistent. "
    "Wie kann ich Ihnen helfen?"
)


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
    Inject the floating chat panel CSS and toggle button.
    Must be called at the very top of main(), before any page content.
    When chat_open=True, call render_panel() at the bottom of main().
    """
    if "chat_messages_global" not in st.session_state:
        st.session_state.chat_messages_global = []
    if "chat_open" not in st.session_state:
        st.session_state.chat_open = False

    # Auto-open on first visit to dashboard or option picker (before option selected)
    if (st.session_state.get("logged_in")
            and not st.session_state.get("_chat_auto_opened")
            and not st.session_state.get("selected_option")):
        st.session_state.chat_open = True
        st.session_state["_chat_auto_opened"] = True

    # Inject CSS for the fixed-position toggle button
    st.markdown(
        f"""
<style>
/* Floating chat toggle pill */
div[data-testid="stVerticalBlock"]:has(button#chat-toggle-btn) {{
    position: fixed !important;
    bottom: 22px !important;
    right: 22px !important;
    z-index: 9999 !important;
    width: auto !important;
}}
button#chat-toggle-btn {{
    background: {HV_GOLD} !important;
    color: {HV_DARK} !important;
    border-radius: 24px !important;
    font-weight: 700 !important;
    padding: 0.5rem 1.2rem !important;
    border: none !important;
    box-shadow: 0 4px 16px rgba(0,0,0,0.4) !important;
}}
</style>
        """,
        unsafe_allow_html=True,
    )

    if not st.session_state.chat_open:
        if st.button("💬 Chat", key="chat-toggle-btn"):
            st.session_state.chat_open = True
            st.rerun()


def render_panel() -> None:
    """
    Render the chat panel. Call this at the bottom of main() when chat_open=True.
    Builds context from session state and makes LLM call on new user input.
    """
    if not st.session_state.chat_messages_global:
        st.session_state.chat_messages_global.append(
            {"role": "assistant", "content": _OPENING_MSG}
        )

    st.markdown("<hr style='border-color:#1A3048;margin:2rem 0 1rem;'/>",
                unsafe_allow_html=True)
    st.markdown(
        f'<div style="display:flex;align-items:center;justify-content:space-between;'
        f'margin-bottom:.75rem;">'
        f'<span style="color:{HV_GOLD};font-weight:600;">💬 HelveVista Chat</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    if st.button("✕ Schliessen", key="chat-close-btn"):
        st.session_state.chat_open = False
        st.rerun()

    for msg in st.session_state.chat_messages_global[-12:]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"], unsafe_allow_html=True)

    user_input = st.chat_input("Ihre Frage…", key="chat_global_input")
    if user_input:
        st.session_state.chat_messages_global.append(
            {"role": "user", "content": user_input}
        )
        ctx = build_chat_context(
            scenario=st.session_state.get("selected_scenario"),
            option=st.session_state.get("selected_option"),
            vs_step=st.session_state.get("vs_step", 1),
            profile=st.session_state.get("profile_data", {}),
            actor_states=st.session_state.get("case", {}).get("actor_states", {}),
        )
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

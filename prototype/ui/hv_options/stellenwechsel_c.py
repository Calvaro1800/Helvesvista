"""
hv_options/stellenwechsel_c.py
-------------------------------
Option C — Ich weiss nicht wo anfangen (Stellenwechsel).
Free-form diagnostic chat. Recommends Option A, B, or D.
"""
from __future__ import annotations
import os
import re
from datetime import datetime, timezone
from uuid import uuid4
import streamlit as st
import anthropic
from core.mongodb_client import save_case as mongo_save
from ui.hv_styles import HV_GOLD, HV_MUTED
from ui.hv_option_chat import render_option_chat

MODEL = "claude-sonnet-4-20250514"

_SYSTEM_PROMPT = (
    "Du bist HelveVista, ein Vorsorge-Assistent. "
    "Der Nutzer weiss nicht, wo er im Bereich Stellenwechsel anfangen soll. "
    "Stelle gezielte Fragen zur Situation (maximal 2 auf einmal). "
    "Wenn du genug weisst, empfehle EXAKT EINE der folgenden Optionen:\n"
    "- Option A: Dokumente verstehen (Nutzer möchte seinen Vorsorgeausweis verstehen)\n"
    "- Option B: Koordination starten (Nutzer hat Job gewechselt und muss koordinieren)\n"
    "- Option D: LPP-Einkauf verstehen (Nutzer interessiert sich für steuerliche Optimierung)\n\n"
    "Antworte immer auf Deutsch. "
    "Empfehle nie mehrere Optionen gleichzeitig. "
    "Wenn du eine Empfehlung gibst, füge am Ende einen neuen Absatz mit genau diesem Format ein:\n"
    "EMPFEHLUNG: [A|B|D]"
)

_OPENING = (
    "Guten Tag! Ich helfe Ihnen, den richtigen Weg im Bereich Stellenwechsel zu finden. "
    "Können Sie mir kurz schildern, was Sie beschäftigt?"
)


def parse_recommendation(text: str) -> str | None:
    """
    Extract 'EMPFEHLUNG: X' from LLM response text.
    Returns the letter ('A', 'B', or 'D') or None if not present.
    """
    match = re.search(r"EMPFEHLUNG:\s*([ABDabd])", text)
    return match.group(1).upper() if match else None


def render(profile: dict, case: dict) -> None:
    scenario = st.session_state.get("selected_scenario", "stellenwechsel")

    st.markdown(
        f'<h2 style="margin-bottom:.25rem;">Wo anfangen?</h2>'
        f'<p style="color:{HV_MUTED};font-size:.88rem;margin-bottom:1.5rem;">'
        f"Beschreiben Sie Ihre Situation. HelveVista analysiert und empfiehlt den richtigen Weg.</p>",
        unsafe_allow_html=True,
    )

    if st.button("← Zurück zur Optionswahl", key="sw_c_back"):
        st.session_state.selected_option = None
        st.rerun()

    msgs_key = "sw_c_messages"
    if msgs_key not in st.session_state:
        st.session_state[msgs_key] = [{"role": "assistant", "content": _OPENING}]

    for msg in st.session_state[msgs_key]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"], unsafe_allow_html=True)

    # Render jump button if last assistant message contains a recommendation
    last_assistant = next(
        (m["content"] for m in reversed(st.session_state[msgs_key])
         if m["role"] == "assistant"), ""
    )
    rec = parse_recommendation(last_assistant)
    if rec:
        if st.button(f"Option {rec} starten →", key=f"sw_c_jump_{rec}", type="primary"):
            st.session_state.selected_option = rec
            st.session_state.option_statuses.setdefault(scenario, {})[rec] = "in_bearbeitung"
            st.rerun()

    st.markdown(
        f'<p style="color:{HV_GOLD};font-size:.8rem;letter-spacing:.1em;margin:1.5rem 0 .4rem;">'
        f"IHRE SITUATION</p>",
        unsafe_allow_html=True,
    )
    _input_cycle = st.session_state.get("sw_c_input_cycle", 0)
    user_input = st.text_area(
        "Ihre Situation",
        placeholder="Beschreiben Sie Ihre Situation…",
        key=f"sw_c_text_{_input_cycle}",
        height=100,
        label_visibility="collapsed",
    )
    col_l, col_btn, col_r = st.columns([3, 2, 3])
    with col_btn:
        send = st.button("Senden →", key="sw_c_send", type="primary", use_container_width=True)
    if send and user_input.strip():
        st.session_state[msgs_key].append({"role": "user", "content": user_input.strip()})
        reply = _llm_reply(st.session_state[msgs_key])
        st.session_state[msgs_key].append({"role": "assistant", "content": reply})
        st.session_state.option_statuses.setdefault(scenario, {}).setdefault("C", "in_bearbeitung")
        st.session_state["sw_c_input_cycle"] = _input_cycle + 1
        st.rerun()

    render_option_chat(
        session_key="chat_c_sw",
        system_prompt=(
            "Du bist HelveVista, ein Experte für die berufliche Vorsorge (Säule 2) in der Schweiz. "
            "Du hilfst Personen, die einen Stellenwechsel vollziehen oder geplant haben, ihre "
            "Vorsorgesituation zu verstehen. Erkläre Freizügigkeit, Pensionskassentransfers, "
            "BVG-Grundlagen und verwandte Themen klar und verständlich auf Deutsch. "
            "Berechne keine Beträge. Antworte immer auf Deutsch."
        ),
        opening_msg="Haben Sie allgemeine Fragen zur beruflichen Vorsorge?",
        title="Allgemeine Vorsorge-Fragen",
        emoji="🗺️",
    )

    st.divider()
    if st.button("Meine Vorsorgesituation speichern", key="close_sw_c"):
        mongo_save(
            case_id=uuid4().hex[:8].upper(),
            user_email=st.session_state.get("user_email", ""),
            scenario="stellenwechsel",
            status="TERMINE",
            data={
                "option": "C",
                "user_name": st.session_state.get("user_name", ""),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
        st.success("Ihre Vorsorgesituation wurde gespeichert. Vielen Dank!")


def _llm_reply(messages: list[dict]) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return "LLM nicht verfügbar (ANTHROPIC_API_KEY fehlt)."
    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=MODEL,
            max_tokens=512,
            system=_SYSTEM_PROMPT,
            messages=[{"role": m["role"], "content": m["content"]} for m in messages[-12:]],
        )
        return resp.content[0].text.strip()
    except Exception as e:
        return f"Fehler: {e}"

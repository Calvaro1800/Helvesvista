"""
hv_options/revue_avs_c.py
--------------------------
Option C — Ich weiss nicht wo anfangen (Revue AVS).
Same pattern as stellenwechsel_c but AVS-focused system prompt.
Recommends Option A, B, or D.
"""
from __future__ import annotations
import os
import re
import streamlit as st
import anthropic
from ui.hv_styles import HV_MUTED

MODEL = "claude-sonnet-4-20250514"

_SYSTEM_PROMPT = (
    "Du bist HelveVista, ein Vorsorge-Assistent. "
    "Der Nutzer weiss nicht, wo er im Bereich AHV / Revue AVS anfangen soll. "
    "Stelle gezielte Fragen zur AHV-Situation (maximal 2 auf einmal). "
    "Wenn du genug weisst, empfehle EXAKT EINE der folgenden Optionen:\n"
    "- Option A: IK-Auszug verstehen (Nutzer möchte seinen IK-Auszug verstehen)\n"
    "- Option B: Anfrage stellen (Nutzer möchte einen aktuellen IK-Auszug bei der AHV beantragen)\n"
    "- Option D: AVS-Lücke schliessen (Nutzer hat Beitragslücken und möchte nachzahlen)\n\n"
    "Antworte immer auf Deutsch. "
    "Empfehle nie mehrere Optionen gleichzeitig. "
    "Wenn du eine Empfehlung gibst, füge am Ende einen neuen Absatz mit genau diesem Format ein:\n"
    "EMPFEHLUNG: [A|B|D]"
)

_OPENING = (
    "Guten Tag! Ich helfe Ihnen, den richtigen Weg im Bereich AHV / Revue AVS zu finden. "
    "Was beschäftigt Sie bezüglich Ihrer AHV-Situation?"
)


def parse_recommendation(text: str) -> str | None:
    match = re.search(r"EMPFEHLUNG:\s*([ABDabd])", text)
    return match.group(1).upper() if match else None


def render(profile: dict, case: dict) -> None:
    scenario = st.session_state.get("selected_scenario", "revue_avs")

    st.markdown(
        f'<h2 style="margin-bottom:.25rem;">Wo anfangen?</h2>'
        f'<p style="color:{HV_MUTED};font-size:.88rem;margin-bottom:1.5rem;">'
        f"Beschreiben Sie Ihre AHV-Situation. HelveVista analysiert und empfiehlt den richtigen Weg.</p>",
        unsafe_allow_html=True,
    )

    if st.button("← Zurück zur Optionswahl", key="avs_c_back"):
        st.session_state.selected_option = None
        st.rerun()

    msgs_key = "avs_c_messages"
    if msgs_key not in st.session_state:
        st.session_state[msgs_key] = [{"role": "assistant", "content": _OPENING}]

    for msg in st.session_state[msgs_key]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"], unsafe_allow_html=True)

    last_assistant = next(
        (m["content"] for m in reversed(st.session_state[msgs_key])
         if m["role"] == "assistant"), ""
    )
    rec = parse_recommendation(last_assistant)
    if rec:
        if st.button(f"Option {rec} starten →", key=f"avs_c_jump_{rec}", type="primary"):
            st.session_state.selected_option = rec
            st.session_state.option_statuses.setdefault(scenario, {})[rec] = "in_bearbeitung"
            st.rerun()

    user_input = st.chat_input("Ihre Situation…", key="avs_c_input")
    if user_input:
        st.session_state[msgs_key].append({"role": "user", "content": user_input})
        reply = _llm_reply(st.session_state[msgs_key])
        st.session_state[msgs_key].append({"role": "assistant", "content": reply})
        st.session_state.option_statuses.setdefault(scenario, {}).setdefault("C", "in_bearbeitung")
        st.rerun()


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

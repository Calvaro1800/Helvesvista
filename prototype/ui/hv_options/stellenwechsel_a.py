"""
hv_options/stellenwechsel_a.py
-------------------------------
Option A — Dokumente verstehen (Stellenwechsel).
User uploads Vorsorgeausweis; HelveVista explains 4 key fields in plain German.
Educational only — no institution contact, no state machine.
"""
from __future__ import annotations
import os
import json
from datetime import datetime, timezone
from uuid import uuid4
import streamlit as st
import anthropic
from core.mongodb_client import save_case as mongo_save
from ui.hv_utils import extract_doc_info
from ui.hv_styles import HV_GOLD, HV_MUTED, HV_BORDER, HV_CARD
from ui.hv_option_chat import render_option_chat

MODEL = "claude-sonnet-4-20250514"

_CHAT_SYSTEM = (
    "Du bist HelveVista, ein Bildungsassistent für das Schweizer BVG-System. "
    "Du hilfst dem Nutzer, Begriffe im Vorsorgeausweis zu verstehen: "
    "Freizügigkeitsguthaben, Koordinationsabzug, Deckungsgrad, Umwandlungssatz. "
    "Klar, ohne Fachjargon, keine Berechnungen. Antworte auf Deutsch."
)
_CHAT_OPENING = "Ihr Vorsorgeausweis wurde erklärt. Haben Sie Fragen zu einem der Begriffe?"

EXPLAINED_FIELDS = ("freizuegigkeit", "koordinationsabzug", "deckungsgrad", "umwandlungssatz")

_FIELD_LABELS = {
    "freizuegigkeit":     "Freizügigkeitsguthaben",
    "koordinationsabzug": "Koordinationsabzug",
    "deckungsgrad":       "Deckungsgrad",
    "umwandlungssatz":    "Umwandlungssatz",
}

_SYSTEM_PROMPT = (
    "Du bist HelveVista, ein Bildungsassistent für das Schweizer BVG-System. "
    "Du erhältst Daten aus einem Vorsorgeausweis. "
    "Erkläre die folgenden vier Felder in einfachem Deutsch — klar, ohne Fachjargon, "
    "ohne Berechnungen, in je 2-3 Sätzen:\n"
    "- Freizügigkeitsguthaben (freizuegigkeit)\n"
    "- Koordinationsabzug (koordinationsabzug)\n"
    "- Deckungsgrad (deckungsgrad)\n"
    "- Umwandlungssatz (umwandlungssatz)\n\n"
    "Antworte NUR mit JSON:\n"
    '{"freizuegigkeit":"...","koordinationsabzug":"...","deckungsgrad":"...","umwandlungssatz":"..."}\n'
    "Wenn ein Wert im Dokument fehlt, erkläre den Begriff trotzdem allgemein."
)


def _explain_fields(extracted: dict) -> dict[str, str]:
    """Call LLM to explain the 4 fields. Returns {field: explanation} or {}."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {}
    try:
        client = anthropic.Anthropic(api_key=api_key)
        context = json.dumps({k: extracted.get(k) for k in (
            "freizuegigkeit_chf", "koordinationsabzug_chf",
            "pensionskasse", "arbeitgeber",
        )}, ensure_ascii=False)
        resp = client.messages.create(
            model=MODEL,
            max_tokens=800,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Dokumentdaten: {context}"}],
        )
        raw = resp.content[0].text.strip().replace("```json", "").replace("```", "")
        return json.loads(raw)
    except Exception:
        return {}


def render(profile: dict, case: dict) -> None:
    scenario = st.session_state.get("selected_scenario", "stellenwechsel")

    st.markdown(
        f'<h2 style="margin-bottom:.25rem;">Dokumente verstehen</h2>'
        f'<p style="color:{HV_MUTED};font-size:.88rem;margin-bottom:1.5rem;">'
        f"Laden Sie Ihren Vorsorgeausweis hoch. HelveVista erklärt jeden Abschnitt.</p>",
        unsafe_allow_html=True,
    )

    if st.button("← Zurück zur Optionswahl", key="sw_a_back"):
        st.session_state.selected_option = None
        st.rerun()

    uploaded = st.file_uploader(
        "Vorsorgeausweis hochladen (PDF, PNG, JPG)",
        type=["pdf", "png", "jpg", "jpeg"],
        key="sw_a_upload",
        accept_multiple_files=True,
    )

    if not uploaded:
        st.info("Bitte laden Sie Ihren Vorsorgeausweis hoch, um fortzufahren.")
        return

    state_key = "sw_a_explanations"
    if state_key not in st.session_state or st.button("Neu analysieren", key="sw_a_reanalyse"):
        with st.spinner("Dokument wird analysiert…"):
            extracted = extract_doc_info(list(uploaded))
            explanations = _explain_fields(extracted)
        st.session_state[state_key] = explanations
        st.session_state["extracted_doc_data"] = extracted
        # Advance option status
        st.session_state.option_statuses.setdefault(scenario, {})["A"] = "geklaert"

    explanations: dict = st.session_state.get(state_key, {})

    if not explanations:
        st.warning("Erklärungen konnten nicht geladen werden. Bitte versuchen Sie es erneut.")
        return

    st.markdown(
        f'<p style="color:{HV_GOLD};font-size:.8rem;letter-spacing:.1em;margin:1rem 0 .5rem;">'
        f"ERKLÄRUNGEN AUS IHREM VORSORGEAUSWEIS</p>",
        unsafe_allow_html=True,
    )

    for field in EXPLAINED_FIELDS:
        label = _FIELD_LABELS[field]
        text  = explanations.get(field, "—")
        with st.expander(label, expanded=True):
            st.markdown(
                f'<p style="color:#C8D8E8;font-size:.88rem;line-height:1.7;">{text}</p>',
                unsafe_allow_html=True,
            )

    st.success("✅ Ihre Dokumente wurden erklärt. Status: Geklärt.")

    render_option_chat(
        session_key="chat_a_sw",
        system_prompt=_CHAT_SYSTEM,
        opening_msg=_CHAT_OPENING,
        title="Fragen zum Vorsorgeausweis",
    )

    st.divider()
    if st.button("Meine Vorsorgesituation speichern", key="close_sw_a"):
        mongo_save(
            case_id=uuid4().hex[:8].upper(),
            user_email=st.session_state.get("user_email", ""),
            scenario="stellenwechsel",
            status="TERMINE",
            data={
                "option": "A",
                "user_name": st.session_state.get("user_name", ""),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
        st.success("Ihre Vorsorgesituation wurde gespeichert. Vielen Dank!")

"""
hv_options/revue_avs_a.py
--------------------------
Option A — IK-Auszug verstehen (Revue AVS).
User uploads AHV individual account statement; HelveVista explains it.
Freshness check: warns if document is older than 12 months.
"""
from __future__ import annotations
import os
import json
from datetime import date
import streamlit as st
import anthropic
from ui.hv_utils import extract_doc_info
from ui.hv_styles import HV_GOLD, HV_MUTED
from ui.hv_option_chat import render_option_chat

MODEL = "claude-sonnet-4-20250514"

_CHAT_SYSTEM = (
    "Du bist HelveVista, ein Bildungsassistent für das Schweizer AHV-System. "
    "Du hilfst dem Nutzer, den IK-Auszug (Individuelles Konto) zu verstehen: "
    "Beitragsjahre, Beitragslücken, freiwillige Nachzahlungen. "
    "Klar, ohne Fachjargon, keine Berechnungen. Antworte auf Deutsch."
)
_CHAT_OPENING = (
    "Ihr IK-Auszug wurde erklärt. "
    "Haben Sie Fragen zu Beitragsjahren, Lücken oder freiwilligen Nachzahlungen?"
)

_SYSTEM_PROMPT = (
    "Du bist HelveVista, ein Bildungsassistent für das Schweizer AHV-System. "
    "Du erhältst Daten aus einem IK-Auszug (Individuelle Kontenauszug). "
    "Erkläre folgende Aspekte in einfachem Deutsch, ohne Berechnungen:\n"
    "1. Beitragsjahre: Was sie bedeuten und warum sie wichtig sind\n"
    "2. Lücken: Was eine Beitragslücke ist und welche Konsequenzen sie hat\n"
    "3. Freiwillige Nachzahlungen: Ob und wann eine Nachzahlung sinnvoll sein kann\n\n"
    "Antworte NUR mit JSON:\n"
    '{"beitragsjahre":"...","luecken":"...","nachzahlungen":"..."}\n'
    "Wenn Daten fehlen, erkläre die Begriffe allgemein. Nur JSON."
)


def is_ik_stale(issued_date_str: str | None, months: int = 12) -> bool:
    """
    Return True if issued_date_str is more than `months` months in the past.
    Returns False for None, empty string, or unparseable dates.
    """
    if not issued_date_str:
        return False
    try:
        issued = date.fromisoformat(str(issued_date_str)[:10])
        today  = date.today()
        delta  = (today.year - issued.year) * 12 + (today.month - issued.month)
        return delta > months
    except (ValueError, TypeError):
        return False


def _explain_ik(extracted: dict) -> dict[str, str]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {}
    try:
        client = anthropic.Anthropic(api_key=api_key)
        context = json.dumps({
            "beitragsjahre": extracted.get("beitragsjahre"),
            "luecken":       extracted.get("luecken"),
            "issued_date":   extracted.get("issued_date"),
        }, ensure_ascii=False)
        resp = client.messages.create(
            model=MODEL,
            max_tokens=600,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"IK-Auszug Daten: {context}"}],
        )
        raw = resp.content[0].text.strip().replace("```json", "").replace("```", "")
        return json.loads(raw)
    except Exception:
        return {}


def render(profile: dict, case: dict) -> None:
    scenario = st.session_state.get("selected_scenario", "revue_avs")

    st.markdown(
        f'<h2 style="margin-bottom:.25rem;">IK-Auszug verstehen</h2>'
        f'<p style="color:{HV_MUTED};font-size:.88rem;margin-bottom:1.5rem;">'
        f"Laden Sie Ihren IK-Auszug hoch. HelveVista erklärt Beitragsjahre und Lücken.</p>",
        unsafe_allow_html=True,
    )

    if st.button("← Zurück zur Optionswahl", key="avs_a_back"):
        st.session_state.selected_option = None
        st.rerun()

    uploaded = st.file_uploader(
        "IK-Auszug hochladen (PDF, PNG, JPG)",
        type=["pdf", "png", "jpg", "jpeg"],
        key="avs_a_upload",
        accept_multiple_files=True,
    )

    if not uploaded:
        st.info("Bitte laden Sie Ihren IK-Auszug (Individuelle Kontenauszug) hoch.")
        return

    state_key = "avs_a_explanations"
    if state_key not in st.session_state or st.button("Neu analysieren", key="avs_a_reanalyse"):
        with st.spinner("IK-Auszug wird analysiert…"):
            extracted = extract_doc_info(list(uploaded))
            explanations = _explain_ik(extracted)
        st.session_state[state_key] = explanations
        st.session_state["avs_a_extracted"] = extracted
        st.session_state.option_statuses.setdefault(scenario, {})["A"] = "geklaert"

    extracted = st.session_state.get("avs_a_extracted", {})
    explanations: dict = st.session_state.get(state_key, {})

    # Freshness warning
    if is_ik_stale(extracted.get("issued_date")):
        st.warning(
            "⚠️ Dieser IK-Auszug wurde vor mehr als 12 Monaten ausgestellt "
            "und ist möglicherweise nicht mehr aktuell. "
            "Beantragen Sie einen neuen Auszug unter ch.ch/ik-auszug."
        )

    if not explanations:
        st.warning("Erklärungen konnten nicht geladen werden. Bitte versuchen Sie es erneut.")
        return

    _LABELS = {
        "beitragsjahre": "Beitragsjahre",
        "luecken":       "Beitragslücken",
        "nachzahlungen": "Freiwillige Nachzahlungen",
    }

    st.markdown(
        f'<p style="color:{HV_GOLD};font-size:.8rem;letter-spacing:.1em;margin:1rem 0 .5rem;">'
        f"ERKLÄRUNGEN AUS IHREM IK-AUSZUG</p>",
        unsafe_allow_html=True,
    )

    for field, label in _LABELS.items():
        with st.expander(label, expanded=True):
            st.markdown(
                f'<p style="color:#C8D8E8;font-size:.88rem;line-height:1.7;">'
                f'{explanations.get(field, "—")}</p>',
                unsafe_allow_html=True,
            )

    st.success("✅ Ihr IK-Auszug wurde erklärt. Status: Geklärt.")

    render_option_chat(
        session_key="chat_a_avs",
        system_prompt=_CHAT_SYSTEM,
        opening_msg=_CHAT_OPENING,
        title="Fragen zum IK-Auszug",
    )

    st.divider()
    if not st.session_state.get("case_done"):
        if st.button("Meine Vorsorgesituation speichern", key="close_avs_a"):
            st.session_state["case_done"] = True
            st.rerun()
    else:
        st.success("Ihre Vorsorgesituation wurde gespeichert. Vielen Dank!")

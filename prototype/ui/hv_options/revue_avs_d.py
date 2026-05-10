"""
hv_options/revue_avs_d.py
--------------------------
Option D — AVS-Lücke schliessen (Revue AVS).
Educates on AHV voluntary contributions; connects to AHV-Ausgleichskasse.
Never calculates amounts.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from uuid import uuid4
import streamlit as st
from core.mongodb_client import save_case as mongo_save
from ui.hv_styles import HV_GOLD, HV_MUTED
from ui.hv_option_chat import render_option_chat

_CHAT_SYSTEM = (
    "Du bist HelveVista, ein Bildungsassistent für das Schweizer AHV-System. "
    "Du hilfst dem Nutzer zu verstehen, wie AHV-Beitragslücken geschlossen werden können. "
    "Themen: Wer ist betroffen, Zeitfenster für Nachzahlungen, Ablauf der Nachzahlung. "
    "Keine konkreten Beträge. Antworte auf Deutsch."
)
_CHAT_OPENING = (
    "Haben Sie Fragen zu freiwilligen AHV-Nachzahlungen "
    "oder zum Schliessen von Beitragslücken?"
)

AVS_SECTIONS: list[dict] = [
    {
        "title": "Wer ist betroffen",
        "content": (
            "Beitragslücken entstehen, wenn jemand in einem Jahr weniger als die Mindestbeiträge "
            "in die AHV eingezahlt hat — etwa durch Erwerbsunterbrechungen, Auslandaufenthalte, "
            "oder Phasen der Selbständigkeit ohne ausreichende Beiträge. "
            "Auch Auslandjahre vor dem 20. Lebensjahr können zu Lücken führen."
        ),
    },
    {
        "title": "Zeitfenster",
        "content": (
            "Freiwillige Nachzahlungen sind grundsätzlich für die letzten 5 Beitragsjahre möglich. "
            "Ausnahmen gelten für Personen, die sich im Ausland befunden haben: "
            "In bestimmten Fällen können ältere Lücken nachgezahlt werden. "
            "Die genauen Fristen und Möglichkeiten klären Sie direkt mit der AHV-Ausgleichskasse."
        ),
    },
    {
        "title": "Ablauf der Nachzahlung",
        "content": (
            "1. Beantragen Sie einen aktuellen IK-Auszug, um Ihre Beitragsjahre zu kennen. "
            "2. Wenden Sie sich an die zuständige AHV-Ausgleichskasse für eine Berechnung. "
            "3. Bezahlen Sie den festgelegten Nachzahlungsbetrag fristgerecht. "
            "4. Die Nachzahlung wird in Ihrer AHV-Beitragshistorie vermerkt."
        ),
    },
]

_DISCLAIMER = (
    "⚠️ HelveVista berechnet keine Beträge. "
    "Die genauen Nachzahlungsbeträge und Fristen erhalten Sie von der AHV-Ausgleichskasse."
)


def render(profile: dict, case: dict) -> None:
    from llm.email_agent import send_institution_email
    from core.states import Actor

    scenario = st.session_state.get("selected_scenario", "revue_avs")

    st.markdown(
        f'<h2 style="margin-bottom:.25rem;">AVS-Lücke schliessen</h2>'
        f'<p style="color:{HV_MUTED};font-size:.88rem;margin-bottom:1.5rem;">'
        f"Verstehen Sie die Regeln für freiwillige Nachzahlungen.</p>",
        unsafe_allow_html=True,
    )

    if st.button("← Zurück zur Optionswahl", key="avs_d_back"):
        st.session_state.selected_option = None
        st.rerun()

    st.warning(_DISCLAIMER)

    for section in AVS_SECTIONS:
        with st.expander(section["title"], expanded=False):
            st.markdown(
                f'<p style="color:#C8D8E8;font-size:.88rem;line-height:1.7;">{section["content"]}</p>',
                unsafe_allow_html=True,
            )

    st.markdown("---")
    st.markdown(
        f'<p style="color:{HV_GOLD};font-size:.9rem;font-weight:600;margin-bottom:.5rem;">'
        f"Genaue Zahlen bei der AHV-Ausgleichskasse anfragen</p>"
        f'<p style="color:{HV_MUTED};font-size:.84rem;margin-bottom:1rem;">'
        f"Die AHV-Ausgleichskasse berechnet den exakten Nachzahlungsbetrag und die Fristen.</p>",
        unsafe_allow_html=True,
    )

    email_input = st.text_input("E-Mail-Adresse Ihrer AHV-Ausgleichskasse",
                                key="avs_d_email",
                                placeholder="info@ausgleichskasse.ch")

    status = st.session_state.option_statuses.get(scenario, {}).get("D", "in_bearbeitung")

    if status in ("anfrage_gesendet", "antwort_erhalten"):
        st.success("📤 Anfrage wurde bereits gesendet.")
    elif st.button("Anfrage senden →", key="avs_d_send", type="primary",
                   disabled=not email_input.strip()):
        minimal_case = {
            "case_id":    case.get("case_id") or uuid.uuid4().hex[:8].upper(),
            "user_name":  st.session_state.get("user_name", ""),
            "user_email": st.session_state.get("user_email", ""),
            "situation":  "AVS-Lücke: Anfrage für genaue Nachzahlungsbeträge.",
            "verfahren":  "AVS-Nachzahlung",
        }
        with st.spinner("E-Mail wird gesendet…"):
            ok = send_institution_email(Actor.AVS, minimal_case, email_input.strip())
        if ok:
            st.session_state.option_statuses.setdefault(scenario, {})["D"] = "anfrage_gesendet"
            st.success("✅ Ihre Anfrage wurde an die AHV-Ausgleichskasse gesendet.")
            st.rerun()
        else:
            st.error("Fehler beim Senden. Bitte prüfen Sie die E-Mail-Adresse.")

    render_option_chat(
        session_key="chat_d_avs",
        system_prompt=_CHAT_SYSTEM,
        opening_msg=_CHAT_OPENING,
        title="Fragen zur AVS-Lückenschliessung",
    )

    st.divider()
    if st.button("Meine Vorsorgesituation speichern", key="close_avs_d"):
        mongo_save(
            case_id=uuid4().hex[:8].upper(),
            user_email=st.session_state.get("user_email", ""),
            scenario="revue_avs",
            status="TERMINE",
            data={
                "option": "D",
                "user_name": st.session_state.get("user_name", ""),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
        st.success("Ihre Vorsorgesituation wurde gespeichert. Vielen Dank!")

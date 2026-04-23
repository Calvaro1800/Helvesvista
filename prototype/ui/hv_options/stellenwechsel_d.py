"""
hv_options/stellenwechsel_d.py
--------------------------------
Option D — LPP-Einkauf verstehen (Stellenwechsel).
Educates on LPP buyback, then connects to Neue PK for a certificate.
Never calculates amounts.
"""
from __future__ import annotations
import streamlit as st
from ui.hv_styles import HV_GOLD, HV_MUTED, HV_BORDER
from ui.hv_option_chat import render_option_chat

_CHAT_SYSTEM = (
    "Du bist HelveVista, ein Bildungsassistent für das Schweizer BVG-System. "
    "Du hilfst dem Nutzer, den freiwilligen Einkauf in die Pensionskasse (LPP-Einkauf) zu verstehen. "
    "Themen: steuerliche Vorteile, Kapitalauswirkung, hypothekarische Implikationen, optimales Timing. "
    "Keine konkreten Berechnungen. Antworte auf Deutsch."
)
_CHAT_OPENING = "Haben Sie Fragen zum freiwilligen Einkauf in Ihre Pensionskasse?"

LPP_SECTIONS: list[dict] = [
    {
        "title": "Steuerliche Vorteile",
        "content": (
            "Ein freiwilliger Einkauf in die Pensionskasse ist steuerlich absetzbar — "
            "der eingekaufte Betrag wird vom steuerbaren Einkommen abgezogen. "
            "Bei höheren Einkommen kann dies zu einer erheblichen Steuerersparnis führen. "
            "Die genaue Höhe hängt von Ihrem Einkommen, Wohnkanton und dem zulässigen Einkaufsbetrag ab."
        ),
    },
    {
        "title": "Kapitalauswirkung",
        "content": (
            "Ein Einkauf erhöht Ihr BVG-Altersguthaben. "
            "Dieses Guthaben wird bei der Pensionierung in eine Rente umgewandelt "
            "oder kann (je nach Reglement) als Kapital bezogen werden. "
            "Beachten Sie: Der mögliche Einkaufsbetrag ist durch die Einkaufslücke begrenzt, "
            "die Ihre Pensionskasse berechnet."
        ),
    },
    {
        "title": "Hypothekarische Implikationen",
        "content": (
            "Wenn Sie Ihr BVG-Guthaben bereits für den Erwerb von Wohneigentum (WEF) "
            "verwendet haben, gelten besondere Wartefristen für den Einkauf. "
            "Ein Vorbezug für Wohneigentum schränkt die steuerliche Absetzbarkeit "
            "eines nachfolgenden Einkaufs ein. "
            "Klären Sie diesen Punkt vor einem Einkauf mit Ihrer Pensionskasse."
        ),
    },
    {
        "title": "Timing und Pensionierung",
        "content": (
            "Ein Einkauf innerhalb von 3 Jahren vor der Pensionierung "
            "ist in der Regel nicht mehr steuerwirksam — "
            "das Guthaben gilt dann als nicht voll eingebracht. "
            "Der optimale Zeitpunkt für einen Einkauf liegt in der Regel "
            "in einem Einkommensjahr mit hoher Steuerprogression, "
            "und mindestens 3 Jahre vor dem Bezugsdatum."
        ),
    },
]

_DISCLAIMER = (
    "⚠️ HelveVista berechnet keine Beträge. "
    "Alle konkreten Zahlen (Einkaufslücke, Steuervorteil, Rentenbetrag) "
    "erhalten Sie ausschliesslich von Ihrer Pensionskasse."
)


def render(profile: dict, case: dict) -> None:
    from llm.email_agent import send_institution_email
    from core.states import Actor
    import uuid

    scenario = st.session_state.get("selected_scenario", "stellenwechsel")

    st.markdown(
        f'<h2 style="margin-bottom:.25rem;">LPP-Einkauf verstehen</h2>'
        f'<p style="color:{HV_MUTED};font-size:.88rem;margin-bottom:1.5rem;">'
        f"Verstehen Sie die Vorteile eines freiwilligen Einkaufs.</p>",
        unsafe_allow_html=True,
    )

    if st.button("← Zurück zur Optionswahl", key="sw_d_back"):
        st.session_state.selected_option = None
        st.rerun()

    st.warning(_DISCLAIMER)

    for section in LPP_SECTIONS:
        with st.expander(section["title"], expanded=False):
            st.markdown(
                f'<p style="color:#C8D8E8;font-size:.88rem;line-height:1.7;">{section["content"]}</p>',
                unsafe_allow_html=True,
            )

    st.markdown("---")
    st.markdown(
        f'<p style="color:{HV_GOLD};font-size:.9rem;font-weight:600;margin-bottom:.5rem;">'
        f"Persönliches Einkaufszertifikat anfragen</p>"
        f'<p style="color:{HV_MUTED};font-size:.84rem;margin-bottom:1rem;">'
        f"Ihre Pensionskasse berechnet die exakte Einkaufslücke und den möglichen Steuervorteil.</p>",
        unsafe_allow_html=True,
    )

    email_input = st.text_input("E-Mail-Adresse Ihrer Pensionskasse (Neue PK)",
                                key="sw_d_pk_email",
                                placeholder="info@pensionskasse.ch")

    status = st.session_state.option_statuses.get(scenario, {}).get("D", "in_bearbeitung")

    if status in ("anfrage_gesendet", "antwort_erhalten"):
        st.success("📤 Anfrage wurde bereits gesendet.")
    elif st.button("Zertifikat anfragen →", key="sw_d_send", type="primary",
                   disabled=not email_input.strip()):
        minimal_case = {
            "case_id":    case.get("case_id") or uuid.uuid4().hex[:8].upper(),
            "user_name":  st.session_state.get("user_name", ""),
            "user_email": st.session_state.get("user_email", ""),
            "situation":  "LPP-Einkauf: Anfrage für persönliches Einkaufszertifikat.",
            "verfahren":  "LPP-Einkauf",
        }
        with st.spinner("E-Mail wird gesendet…"):
            ok = send_institution_email(Actor.NEW_PK, minimal_case, email_input.strip())
        if ok:
            st.session_state.option_statuses.setdefault(scenario, {})["D"] = "anfrage_gesendet"
            st.success("✅ Ihre Anfrage wurde an die Pensionskasse gesendet.")
            st.rerun()
        else:
            st.error("Fehler beim Senden. Bitte prüfen Sie die E-Mail-Adresse.")

    render_option_chat(
        session_key="chat_d_sw",
        system_prompt=_CHAT_SYSTEM,
        opening_msg=_CHAT_OPENING,
        title="Fragen zum LPP-Einkauf",
    )

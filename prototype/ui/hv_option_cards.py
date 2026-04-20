"""
ui/hv_option_cards.py
---------------------
Per-scenario A/B/C/D option picker with status badges.
Sets st.session_state.selected_option on click.
"""
from __future__ import annotations
import streamlit as st
from ui.hv_styles import HV_CARD, HV_BORDER, HV_GOLD, HV_MUTED, HV_GREEN, HV_BLUE, HV_DIM, HV_TEXT

_OPTION_CONFIG: dict[str, list[dict]] = {
    "stellenwechsel": [
        {
            "letter": "A",
            "title": "Dokumente verstehen",
            "description": "Laden Sie Ihren Vorsorgeausweis hoch. HelveVista erklärt jeden Abschnitt auf verständlichem Deutsch.",
        },
        {
            "letter": "B",
            "title": "Démarches starten",
            "description": "Der vollständige 6-Schritt-Koordinationsprozess mit Ihren Pensionskassen.",
        },
        {
            "letter": "C",
            "title": "Ich weiss nicht wo anfangen",
            "description": "Beschreiben Sie Ihre Situation. HelveVista analysiert und empfiehlt den richtigen Weg.",
        },
        {
            "letter": "D",
            "title": "LPP-Einkauf verstehen",
            "description": "Verstehen Sie die Vorteile eines freiwilligen Einkaufs und beantragen Sie ein persönliches Zertifikat.",
        },
    ],
    "revue_avs": [
        {
            "letter": "A",
            "title": "IK-Auszug verstehen",
            "description": "Laden Sie Ihren IK-Auszug hoch. HelveVista erklärt Beitragsjahre, Lücken und Konsequenzen.",
        },
        {
            "letter": "B",
            "title": "Anfrage stellen",
            "description": "Strukturierte Anfrage an die AHV-Ausgleichskasse über den Gmail-Kanal.",
        },
        {
            "letter": "C",
            "title": "Ich weiss nicht wo anfangen",
            "description": "Beschreiben Sie Ihre Situation. HelveVista analysiert und empfiehlt den richtigen Weg.",
        },
        {
            "letter": "D",
            "title": "AVS-Lücke schliessen",
            "description": "Verstehen Sie die Regeln für freiwillige Nachzahlungen und beantragen Sie konkrete Zahlen.",
        },
    ],
}

_STATUS_MAP: dict[str, tuple[str, str]] = {
    "not_started":      ("—",                 HV_DIM),
    "in_bearbeitung":   ("◉ In Bearbeitung",  HV_GOLD),
    "in_klaerung":      ("◎ In Klärung",      "#A08030"),
    "geklaert":         ("✅ Geklärt",          HV_GREEN),
    "anfrage_gesendet": ("📤 Anfrage gesendet", HV_BLUE),
    "antwort_erhalten": ("📨 Antwort erhalten", HV_GREEN),
    "warten":           ("⏳ Warten",           HV_MUTED),
}


def get_status_badge(status: str) -> tuple[str, str]:
    """Return (label, color) for a status key. Falls back to not_started."""
    return _STATUS_MAP.get(status, _STATUS_MAP["not_started"])


def get_option_config(scenario: str) -> list[dict]:
    """Return list of 4 option dicts for a scenario, or [] if unknown."""
    return _OPTION_CONFIG.get(scenario, [])


def render(scenario: str) -> None:
    """Render the 2×2 option picker for the given scenario."""
    label = "STELLENWECHSEL" if scenario == "stellenwechsel" else "REVUE AVS"
    statuses: dict = st.session_state.option_statuses.get(scenario, {})
    options = get_option_config(scenario)

    st.markdown(
        f'<h2 style="margin-bottom:.25rem;">{label}</h2>'
        f'<p style="color:{HV_MUTED};font-size:.88rem;margin-bottom:1.5rem;">'
        f"Wie möchten Sie vorgehen?</p>",
        unsafe_allow_html=True,
    )

    if st.button("← Zurück", key="btn_back_to_dashboard"):
        st.session_state.selected_scenario = None
        st.rerun()

    for row_start in (0, 2):
        cols = st.columns(2)
        for i, col in enumerate(cols):
            opt = options[row_start + i]
            with col:
                _render_option_card(opt, statuses.get(opt["letter"], "not_started"), scenario)
        st.markdown("<div style='margin-top:12px;'></div>", unsafe_allow_html=True)


def _render_option_card(opt: dict, status: str, scenario: str) -> None:
    badge_label, badge_color = get_status_badge(status)
    st.markdown(
        f"""
<div style="background:{HV_CARD};border:1px solid {HV_BORDER};border-radius:10px;
            padding:20px;min-height:180px;margin-bottom:4px;">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">
    <span style="background:{HV_GOLD};color:{HV_CARD};font-weight:700;
                 border-radius:4px;padding:2px 10px;font-size:1rem;">{opt["letter"]}</span>
    <span style="color:{badge_color};font-size:.78rem;">{badge_label}</span>
  </div>
  <p style="color:#FFF;font-size:.95rem;font-weight:600;margin:0 0 .4rem;">{opt["title"]}</p>
  <p style="color:{HV_MUTED};font-size:.82rem;line-height:1.6;margin:0 0 .75rem;">{opt["description"]}</p>
</div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Wählen →", key=f"btn_opt_{scenario}_{opt['letter']}", type="primary",
                 use_container_width=True):
        st.session_state.selected_option = opt["letter"]
        statuses = st.session_state.option_statuses.setdefault(scenario, {})
        if opt["letter"] not in statuses:
            statuses[opt["letter"]] = "in_bearbeitung"
        st.rerun()

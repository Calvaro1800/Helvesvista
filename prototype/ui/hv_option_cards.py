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
            "title": "Koordinationsverfahren einleiten",
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
            "title": "Koordinationsverfahren einleiten",
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

# Profile fields that signal meaningful data has been collected
_PROFILE_MEANINGFUL = ("vorname", "geburtsjahr")

# Keys that indicate extracted document data exists
_DOC_KEYS = (
    "freizuegigkeit_chf", "ahv_nummer", "koordinationsabzug_chf",
    "ik_auszug", "beitragsjahre",
)

# What each option still needs from the user (shown in the reuse summary)
_OPTION_MISSING: dict[str, dict[str, str]] = {
    "stellenwechsel": {
        "A": "Vorsorgeausweis (PDF oder Bild)",
        "B": "Angaben zu alter und neuer Pensionskasse",
        "C": "Kurze Beschreibung Ihrer Situation",
        "D": "Vorsorgeausweis und Angaben zum geplanten Einkauf",
    },
    "revue_avs": {
        "A": "IK-Auszug (PDF oder Bild)",
        "B": "Kontaktdaten der AHV-Ausgleichskasse",
        "C": "Kurze Beschreibung Ihrer Situation",
        "D": "IK-Auszug und Informationen zu Beitragslücken",
    },
}


def get_status_badge(status: str) -> tuple[str, str]:
    """Return (label, color) for a status key. Falls back to not_started."""
    return _STATUS_MAP.get(status, _STATUS_MAP["not_started"])


def get_option_config(scenario: str) -> list[dict]:
    """Return list of 4 option dicts for a scenario, or [] if unknown."""
    return _OPTION_CONFIG.get(scenario, [])


def _has_reusable_data() -> bool:
    """True when profile has meaningful fields AND extracted document data exists."""
    profile = st.session_state.get("profile_data", {})
    if not any(profile.get(k) for k in _PROFILE_MEANINGFUL):
        return False
    for source_key in ("extracted_doc_data", "extracted_doc_info"):
        doc = st.session_state.get(source_key) or {}
        if any(doc.get(k) for k in _DOC_KEYS):
            return True
    return any(profile.get(k) for k in _DOC_KEYS)


def _fmt_chf(val) -> str:
    try:
        cleaned = str(val).replace("'", "").replace(",", "").strip()
        return f"CHF {float(cleaned):,.0f}"
    except (ValueError, TypeError):
        return f"CHF {val}"


def _data_summary(scenario: str, option: str) -> str:
    """Return a markdown block listing known data and what's still needed."""
    profile = st.session_state.get("profile_data", {})
    extracted = (
        st.session_state.get("extracted_doc_data")
        or st.session_state.get("extracted_doc_info")
        or {}
    )
    lines = ["**Bekannte Daten:**"]
    if profile.get("vorname"):
        name = f"{profile['vorname']} {profile.get('nachname', '')}".strip()
        lines.append(f"- Name: {name}")
    if profile.get("geburtsjahr"):
        lines.append(f"- Geburtsjahr: {profile['geburtsjahr']}")
    if extracted.get("freizuegigkeit_chf"):
        lines.append(f"- Freizügigkeitsguthaben: {_fmt_chf(extracted['freizuegigkeit_chf'])}")
    if extracted.get("ahv_nummer"):
        lines.append(f"- AHV-Nummer: {extracted['ahv_nummer']}")
    if extracted.get("koordinationsabzug_chf"):
        lines.append(f"- Koordinationsabzug: {_fmt_chf(extracted['koordinationsabzug_chf'])}")
    if extracted.get("beitragsjahre"):
        lines.append(f"- Beitragsjahre AHV: {extracted['beitragsjahre']}")
    missing = _OPTION_MISSING.get(scenario, {}).get(option)
    if missing:
        lines.append(f"\n**Noch benötigt für Option {option}:** {missing}")
    return "\n".join(lines)


def render(scenario: str) -> None:
    """Render the 2×2 option picker for the given scenario."""
    pending = st.session_state.get("pending_option")
    if pending:
        _render_reuse_prompt(scenario, pending)
        return

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


def _render_reuse_prompt(scenario: str, option: str) -> None:
    """Show the data-reuse prompt, or skip directly to the option if no data exists."""
    if not _has_reusable_data():
        st.session_state.selected_option = option
        st.session_state.pop("pending_option", None)
        st.session_state["data_reuse_choice"] = "fresh"
        st.session_state.option_statuses.setdefault(scenario, {}).setdefault(option, "in_bearbeitung")
        st.rerun()
        return

    st.markdown(
        '<h2 style="margin-bottom:.25rem;">Daten übernehmen?</h2>'
        f'<p style="color:{HV_MUTED};font-size:.88rem;margin-bottom:1.2rem;">'
        "Möchten Sie mit den bereits hochgeladenen Daten fortfahren?</p>",
        unsafe_allow_html=True,
    )

    with st.container(border=True):
        st.markdown(_data_summary(scenario, option))

    col_ja, col_nein = st.columns(2)
    with col_ja:
        if st.button(
            "Ja, Daten übernehmen",
            key="btn_reuse_ja",
            type="primary",
            use_container_width=True,
        ):
            st.session_state.selected_option = option
            st.session_state.pop("pending_option", None)
            st.session_state["data_reuse_choice"] = "reuse"
            st.session_state.option_statuses.setdefault(scenario, {}).setdefault(option, "in_bearbeitung")
            st.rerun()
    with col_nein:
        if st.button(
            "Nein, neu beginnen",
            key="btn_reuse_nein",
            use_container_width=True,
        ):
            st.session_state.selected_option = option
            st.session_state.pop("pending_option", None)
            st.session_state["data_reuse_choice"] = "fresh"
            st.session_state["extracted_doc_data"] = {}
            st.session_state.option_statuses.setdefault(scenario, {}).setdefault(option, "in_bearbeitung")
            st.rerun()

    st.markdown("<div style='margin-top:.5rem;'></div>", unsafe_allow_html=True)
    if st.button("← Zurück zur Optionswahl", key="btn_reuse_back"):
        st.session_state.pop("pending_option", None)
        st.rerun()


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
    if st.button(
        "Wählen →",
        key=f"btn_opt_{scenario}_{opt['letter']}",
        type="primary",
        use_container_width=True,
    ):
        st.session_state.pop("data_reuse_choice", None)
        st.session_state["pending_option"] = opt["letter"]
        st.rerun()

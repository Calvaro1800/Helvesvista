"""
ui/hv_dashboard.py
------------------
Scenario selection page for HelveVista 2.0.
Replaces _scenario_selection_page() in user_app.py.
Sets st.session_state.selected_scenario on click.
"""
from __future__ import annotations
import streamlit as st
from ui.hv_styles import HV_CARD, HV_BORDER, HV_GOLD, HV_MUTED, HV_DIM, HV_TEXT

SCENARIO_CARDS: list[dict] = [
    {
        "id":          "stellenwechsel",
        "icon":        "⚡",
        "title":       "STELLENWECHSEL",
        "description": "Koordination Ihres BVG-Guthabens beim Wechsel des Arbeitgebers.",
        "actors":      ["Alte PK", "Neue PK", "AHV (optional)"],
        "active":      True,
    },
    {
        "id":          "revue_avs",
        "icon":        "📋",
        "title":       "REVUE AVS",
        "description": "IK-Auszug, Beitragslücken und freiwillige Nachzahlungen.",
        "actors":      ["AHV-Ausgleichskasse", "Optionale PK"],
        "active":      True,
    },
    {
        "id":          "zivilstand",
        "icon":        "♥",
        "title":       "ZIVILSTANDSÄNDERUNG",
        "description": "Meldung einer Heirat, Scheidung oder eines Todesfalls.",
        "actors":      [],
        "active":      False,
    },
    {
        "id":          "pensionierung",
        "icon":        "⏰",
        "title":       "PENSIONIERUNG",
        "description": "AHV, BVG und Säule 3a für einen optimalen Übertritt.",
        "actors":      [],
        "active":      False,
    },
]


def render() -> None:
    """Render the scenario selection page."""
    st.markdown(
        f"""
<div style="text-align:center; padding:3rem 0 0.75rem 0;">
  <span style="color:{HV_GOLD};font-size:3.5rem;font-weight:700;letter-spacing:.12em;">Helve</span><span
        style="color:#FFF;font-size:3.5rem;font-weight:200;letter-spacing:.12em;">Vista</span>
</div>
<p style="text-align:center;color:{HV_MUTED};font-size:.88rem;margin:.25rem 0 1.25rem;letter-spacing:.02em;">
  Koordination Ihrer Vorsorge — einfach, sicher, digital.
</p>
<hr style="border-color:{HV_BORDER};margin:0 0 1.25rem 0;"/>
        """,
        unsafe_allow_html=True,
    )

    cards = SCENARIO_CARDS
    for row_start in (0, 2):
        cols = st.columns(2)
        for i, col in enumerate(cols):
            card = cards[row_start + i]
            with col:
                _render_card(card)
        st.markdown("<div style='margin-top:14px;'></div>", unsafe_allow_html=True)

    st.markdown(
        f'<p style="text-align:center;color:{HV_DIM};font-size:.68rem;'
        f'letter-spacing:.12em;margin-top:2.5rem;">'
        f"HelveVista — Bachelorarbeit ZHAW 2026</p>",
        unsafe_allow_html=True,
    )


def _render_card(card: dict) -> None:
    opacity = "1" if card["active"] else "0.45"
    actor_tags = "  ".join(
        f'<span style="background:{HV_BORDER};color:{HV_MUTED};'
        f'border-radius:3px;padding:1px 7px;font-size:.75rem;">{a}</span>'
        for a in card["actors"]
    )
    st.markdown(
        f"""
<div style="background:{HV_CARD};border:1px solid {HV_BORDER};border-radius:10px;
            padding:24px;min-height:200px;opacity:{opacity};margin-bottom:4px;">
  <div style="font-size:1.5rem;margin-bottom:8px;">{card["icon"]}</div>
  <p style="color:#FFF;font-size:1rem;font-weight:600;letter-spacing:.03em;
             margin:0 0 .5rem;">{card["title"]}</p>
  <p style="color:{HV_MUTED};font-size:.84rem;line-height:1.65;margin:0 0 .75rem;">
    {card["description"]}</p>
  <div style="margin-bottom:.75rem;">{actor_tags}</div>
</div>
        """,
        unsafe_allow_html=True,
    )
    if card["active"]:
        if st.button("Jetzt starten →", key=f"btn_{card['id']}", type="primary",
                     use_container_width=True):
            st.session_state.selected_scenario = card["id"]
            st.rerun()
    else:
        st.markdown(
            f'<p style="color:{HV_DIM};font-size:.78rem;letter-spacing:.1em;'
            f'text-align:center;">In Entwicklung</p>',
            unsafe_allow_html=True,
        )

"""
ui/hv_profile.py
----------------
Universal user profile for HelveVista 2.0.
Collected once after login; persisted to MongoDB user_profiles collection.
On return visits, loaded silently without showing the form.
"""
from __future__ import annotations
import os
import streamlit as st
from ui.hv_styles import HV_GOLD, HV_MUTED, HV_BORDER, HV_CARD, HV_TEXT

_REQUIRED = ("vorname", "nachname", "zivilstand", "geburtsjahr", "anstellung")

_ZIVILSTAND_OPTIONS = ["ledig", "verheiratet", "geschieden", "verwitwet"]
_ANSTELLUNG_OPTIONS = ["angestellt", "selbständig", "arbeitslos", "anderes"]


# ── Pure logic (testable without Streamlit) ──────────────────────────────────

def profile_is_complete(profile: dict) -> bool:
    """Return True only when all required fields are present and non-empty."""
    for field in _REQUIRED:
        val = profile.get(field)
        if val is None or val == "" or val == 0:
            return False
    return True


# ── MongoDB persistence (silent fallback) ────────────────────────────────────

def _get_profiles_collection():
    try:
        from pymongo import MongoClient
        from pymongo.server_api import ServerApi
        uri = os.environ.get("MONGODB_URI")
        if not uri:
            return None
        client = MongoClient(uri, server_api=ServerApi("1"),
                             serverSelectionTimeoutMS=3000)
        return client["helvevista"]["user_profiles"]
    except Exception:
        return None


def load_profile(user_email: str) -> dict | None:
    """Return the stored profile for user_email, or None if not found."""
    col = _get_profiles_collection()
    if col is None:
        return None
    try:
        doc = col.find_one({"user_email": user_email}, {"_id": 0})
        return doc
    except Exception:
        return None


def save_profile(user_email: str, profile: dict) -> bool:
    """Upsert the profile document. Returns True on success."""
    col = _get_profiles_collection()
    if col is None:
        return False
    try:
        from datetime import datetime, timezone
        col.update_one(
            {"user_email": user_email},
            {"$set": {**profile, "user_email": user_email,
                      "updated_at": datetime.now(timezone.utc)},
             "$setOnInsert": {"created_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
        return True
    except Exception:
        return False


# ── Streamlit UI ─────────────────────────────────────────────────────────────

def render() -> None:
    """
    Show the profile form on first visit.
    On return visits: try loading from MongoDB silently.
    Sets st.session_state.profile_complete = True when done.
    """
    user_email = st.session_state.get("user_email", "")
    user_name  = st.session_state.get("user_name", "")

    # Try loading from MongoDB first (silent, no spinner)
    if user_email and not st.session_state.profile_data:
        stored = load_profile(user_email)
        if stored and profile_is_complete(stored):
            st.session_state.profile_data = stored
            st.session_state.profile_complete = True
            st.rerun()
            return

    # Parse name from login
    name_parts = user_name.strip().split(" ", 1)
    default_vorname  = name_parts[0] if name_parts else ""
    default_nachname = name_parts[1] if len(name_parts) > 1 else ""

    st.markdown(
        f'<h2 style="margin-bottom:.25rem;">Ihr Profil</h2>'
        f'<p style="color:{HV_MUTED};font-size:.88rem;margin-bottom:1.5rem;">'
        f"Diese Angaben werden einmalig gespeichert und für alle Szenarien verwendet.</p>",
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2)
    with col1:
        vorname = st.text_input("Vorname", value=default_vorname)
    with col2:
        nachname = st.text_input("Nachname", value=default_nachname)

    col3, col4 = st.columns(2)
    with col3:
        zivilstand = st.selectbox("Zivilstand", [""] + _ZIVILSTAND_OPTIONS)
    with col4:
        geburtsjahr = st.number_input("Geburtsjahr", min_value=1930, max_value=2005,
                                      value=1985, step=1)

    col5, col6 = st.columns(2)
    with col5:
        anstellung = st.selectbox("Beschäftigungsstatus", [""] + _ANSTELLUNG_OPTIONS)
    with col6:
        kinder = st.checkbox("Kinder vorhanden")

    if st.button("Profil speichern", type="primary", use_container_width=True,
                 disabled=not all([vorname, nachname, zivilstand, anstellung])):
        profile = {
            "vorname":    vorname.strip(),
            "nachname":   nachname.strip(),
            "zivilstand": zivilstand,
            "geburtsjahr": int(geburtsjahr),
            "kinder":     kinder,
            "anstellung": anstellung,
        }
        st.session_state.profile_data = profile
        st.session_state.profile_complete = True
        save_profile(user_email, profile)
        st.rerun()

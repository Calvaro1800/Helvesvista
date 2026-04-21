"""
hv_options/revue_avs_b.py
--------------------------
Option B — Anfrage stellen (Revue AVS).
Thin wrapper: ensures selected_scenario = 'revue_avs',
then returns control to the existing step flow in main().
The actual rendering is done by _vs_step_* functions — nothing happens here.
"""
from __future__ import annotations
import streamlit as st


def render(profile: dict, case: dict) -> None:
    """
    This function is intentionally a no-op.
    main() routes revue_avs + B to the existing _vs_step_* flow directly,
    so render() is only called if routing logic changes in the future.
    """
    st.info(
        "Revue AVS — Anfrage stellen: Sie werden zum geführten Prozess weitergeleitet."
    )

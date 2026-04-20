"""
tests/test_helvevista_2.py
--------------------------
Unit tests for HelveVista 2.0 pure-logic functions.
These tests do NOT import Streamlit and do NOT make LLM calls.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui.hv_utils import extract_doc_info
from ui.hv_dashboard import SCENARIO_CARDS


def test_extract_doc_info_empty_list_returns_empty_dict():
    result = extract_doc_info([])
    assert result == {}


def test_scenario_cards_have_required_keys():
    required = {"id", "title", "description", "actors", "active"}
    for card in SCENARIO_CARDS:
        assert required.issubset(card.keys()), f"Missing keys in card: {card}"


def test_active_scenarios_are_stellenwechsel_and_revue_avs():
    active_ids = {c["id"] for c in SCENARIO_CARDS if c["active"]}
    assert active_ids == {"stellenwechsel", "revue_avs"}

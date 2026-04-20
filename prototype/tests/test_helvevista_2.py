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
from ui.hv_option_cards import get_status_badge, get_option_config


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


def test_status_badge_returns_label_and_color_for_all_states():
    states = ["not_started", "in_bearbeitung", "in_klaerung",
              "geklaert", "anfrage_gesendet", "antwort_erhalten", "warten"]
    for s in states:
        label, color = get_status_badge(s)
        assert isinstance(label, str) and len(label) > 0
        assert color.startswith("#")


def test_get_option_config_returns_four_options_per_scenario():
    for scenario in ("stellenwechsel", "revue_avs"):
        opts = get_option_config(scenario)
        assert len(opts) == 4
        letters = {o["letter"] for o in opts}
        assert letters == {"A", "B", "C", "D"}


def test_get_option_config_unknown_scenario_returns_empty():
    assert get_option_config("unknown") == []

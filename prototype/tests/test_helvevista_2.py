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


# ── Task 4: hv_chat ──────────────────────────────────────────────────────────

from ui.hv_chat import build_chat_context


def test_build_chat_context_includes_required_keys():
    ctx = build_chat_context(
        scenario="stellenwechsel",
        option="B",
        vs_step=3,
        profile={"vorname": "Max", "anstellung": "angestellt"},
        actor_states={"OLD_PK": "COMPLETED"},
    )
    assert "scenario" in ctx
    assert "option" in ctx
    assert "vs_step" in ctx
    assert ctx["scenario"] == "stellenwechsel"
    assert ctx["vs_step"] == 3


def test_build_chat_context_handles_none_option():
    ctx = build_chat_context(
        scenario=None, option=None, vs_step=1, profile={}, actor_states={}
    )
    assert ctx["scenario"] == "—"
    assert ctx["option"] == "—"


# ── Task 5: hv_profile ───────────────────────────────────────────────────────

from ui.hv_profile import profile_is_complete


def test_profile_is_complete_returns_false_when_missing_required_field():
    incomplete = {
        "vorname": "Max", "nachname": "Muster",
        "geburtsjahr": 1985, "kinder": False,
        # missing: zivilstand, anstellung
    }
    assert profile_is_complete(incomplete) is False


def test_profile_is_complete_returns_true_when_all_fields_present():
    complete = {
        "vorname": "Max", "nachname": "Muster",
        "zivilstand": "ledig", "geburtsjahr": 1985,
        "kinder": False, "anstellung": "angestellt",
    }
    assert profile_is_complete(complete) is True


def test_profile_is_complete_rejects_empty_string_fields():
    profile = {
        "vorname": "Max", "nachname": "Muster",
        "zivilstand": "",   # empty string = not filled
        "geburtsjahr": 1985, "kinder": False,
        "anstellung": "angestellt",
    }
    assert profile_is_complete(profile) is False


# ── Task 6: stellenwechsel_a ─────────────────────────────────────────────────

from ui.hv_options.stellenwechsel_a import EXPLAINED_FIELDS


def test_stellenwechsel_a_explains_all_four_fields():
    assert set(EXPLAINED_FIELDS) == {
        "freizuegigkeit", "koordinationsabzug", "deckungsgrad", "umwandlungssatz"
    }


# ── Task 7: stellenwechsel_c ─────────────────────────────────────────────────

from ui.hv_options.stellenwechsel_c import parse_recommendation


def test_parse_recommendation_detects_option_B():
    text = "Ich empfehle Ihnen Option B, da Sie bereits einen Arbeitgeberwechsel vollzogen haben.\n\nEMPFEHLUNG: B"
    assert parse_recommendation(text) == "B"


def test_parse_recommendation_returns_none_when_absent():
    text = "Können Sie mir mehr über Ihre Situation erzählen?"
    assert parse_recommendation(text) is None


def test_parse_recommendation_case_insensitive():
    assert parse_recommendation("EMPFEHLUNG: a") == "A"


# ── Task 8: stellenwechsel_d ─────────────────────────────────────────────────

from ui.hv_options.stellenwechsel_d import LPP_SECTIONS


def test_lpp_sections_has_four_entries():
    assert len(LPP_SECTIONS) == 4


def test_lpp_sections_have_title_and_content():
    for s in LPP_SECTIONS:
        assert "title" in s and "content" in s
        assert len(s["content"]) > 20

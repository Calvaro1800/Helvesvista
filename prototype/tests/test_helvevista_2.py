"""
tests/test_helvevista_2.py
--------------------------
Unit tests for HelveVista 2.0 pure-logic functions.
These tests do NOT import Streamlit and do NOT make LLM calls.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui.hv_utils import extract_doc_info


def test_extract_doc_info_empty_list_returns_empty_dict():
    result = extract_doc_info([])
    assert result == {}

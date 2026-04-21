# HelveVista 2.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a scenario dashboard, per-scenario A/B/C/D option routing, floating chat assistant, and universal user profile to the existing HelveVista prototype without modifying any existing step functions or the core/llm layers.

**Architecture:** Slim Router (Approach B) — new features live in dedicated modules under `prototype/ui/`. `user_app.py` is extended only at its imports and `main()` router. All existing `_vs_step_*` and `_inst_*` functions are untouched.

**Tech Stack:** Python 3.11, Streamlit, Anthropic Claude API (`claude-sonnet-4-20250514`), MongoDB Atlas (pymongo), pytest

**Spec:** `docs/superpowers/specs/2026-04-20-helvevista-2.0-design.md`

---

## File Map

**Create:**
```
prototype/ui/hv_styles.py              # CSS color/style constants
prototype/ui/hv_utils.py              # extract_doc_info (moved), LLM client
prototype/ui/hv_profile.py            # profile UI + MongoDB user_profiles collection
prototype/ui/hv_dashboard.py          # scenario selection page
prototype/ui/hv_option_cards.py       # A/B/C/D option picker + status badges
prototype/ui/hv_chat.py               # floating chat panel
prototype/ui/hv_options/__init__.py
prototype/ui/hv_options/stellenwechsel_a.py
prototype/ui/hv_options/stellenwechsel_c.py
prototype/ui/hv_options/stellenwechsel_d.py
prototype/ui/hv_options/revue_avs_a.py
prototype/ui/hv_options/revue_avs_b.py
prototype/ui/hv_options/revue_avs_c.py
prototype/ui/hv_options/revue_avs_d.py
prototype/tests/test_helvevista_2.py  # unit tests for pure-logic functions
```

**Modify:**
```
prototype/ui/user_app.py              # imports + _init_session + main() routing only
```

---

## Task 1: Shared foundation — hv_styles.py, hv_utils.py, session state

**Files:**
- Create: `prototype/ui/hv_styles.py`
- Create: `prototype/ui/hv_utils.py`
- Create: `prototype/tests/test_helvevista_2.py`
- Modify: `prototype/ui/user_app.py` (imports + `_init_session` + delete old `_extract_doc_info` body)

- [ ] **Step 1: Write the failing test**

  Create `prototype/tests/test_helvevista_2.py`:

  ```python
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
  ```

- [ ] **Step 2: Run test to verify it fails**

  ```bash
  cd prototype && python -m pytest tests/test_helvevista_2.py -v
  ```
  Expected: `ImportError` or `ModuleNotFoundError` for `ui.hv_utils`.

- [ ] **Step 3: Create hv_styles.py**

  Create `prototype/ui/hv_styles.py`:

  ```python
  """ui/hv_styles.py — HelveVista 2.0 design tokens."""

  HV_DARK   = "#0F1E2E"
  HV_CARD   = "#122033"
  HV_BORDER = "#1A3048"
  HV_GOLD   = "#C9A84C"
  HV_MUTED  = "#7A96B0"
  HV_GREEN  = "#6FCF97"
  HV_BLUE   = "#56B0E8"
  HV_TEXT   = "#C8D8E8"
  HV_DIM    = "#3E5F7A"
  ```

- [ ] **Step 4: Create hv_utils.py** (extract_doc_info moved here from user_app.py)

  Create `prototype/ui/hv_utils.py`:

  ```python
  """
  ui/hv_utils.py
  --------------
  Shared utilities for HelveVista 2.0 option modules.
  extract_doc_info is here instead of user_app.py to avoid circular imports.
  """
  from __future__ import annotations

  import base64
  import io
  import json
  import os
  import sys

  import anthropic

  MODEL = "claude-sonnet-4-20250514"


  def get_llm_client() -> anthropic.Anthropic:
      api_key = os.environ.get("ANTHROPIC_API_KEY")
      if not api_key:
          raise EnvironmentError("ANTHROPIC_API_KEY not set")
      return anthropic.Anthropic(api_key=api_key)


  def extract_doc_info(uploaded_files: list) -> dict:
      """
      Extract pension/contact information from uploaded documents via Claude API.
      Supports PDF (text via pypdf) and images (PNG/JPG via base64 vision).
      Returns {} if nothing extracted or on any error.
      """
      try:
          import pypdf  # type: ignore[import]
          _PYPDF_OK = True
      except ImportError:
          _PYPDF_OK = False
          print("[extract] WARNING: pypdf not installed — PDF text extraction disabled",
                file=sys.stderr)

      if not uploaded_files:
          return {}

      client = get_llm_client()
      content_parts: list[dict] = []

      for f in uploaded_files:
          file_ext = f.name.lower().rsplit(".", 1)[-1]

          if file_ext == "pdf":
              if not _PYPDF_OK:
                  continue
              try:
                  f.seek(0)
                  reader = pypdf.PdfReader(io.BytesIO(f.read()))
                  text = "".join(p.extract_text() or "" for p in reader.pages)
                  if not text.strip():
                      continue
              except Exception:
                  continue
              content_parts.append({
                  "type": "text",
                  "text": f"Dokument '{f.name}':\n{text[:4000]}",
              })
          else:
              f.seek(0)
              raw = f.read()
              media_map = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}
              media_type = media_map.get(file_ext, "image/png")
              content_parts.append({
                  "type": "image",
                  "source": {"type": "base64", "media_type": media_type,
                             "data": base64.b64encode(raw).decode()},
              })

      if not content_parts:
          return {}

      content_parts.append({
          "type": "text",
          "text": "Extrahiere die Vorsorge-Informationen aus diesem Dokument.",
      })

      system_prompt = (
          "Analysiere dieses Dokument und extrahiere alle verfügbaren Informationen. "
          "Antworte NUR mit JSON:\n"
          '{"name":null,"geburtsdatum":null,"ahv_nummer":null,"pensionskasse":null,'
          '"arbeitgeber":null,"arbeitgeber_ort":null,"freizuegigkeit_chf":null,'
          '"koordinationsabzug_chf":null,"austrittsdatum":null,"eintrittsdatum":null,'
          '"email":null,"telefon":null,"issued_date":null}\n'
          "issued_date: Datum des Dokuments als ISO-String (YYYY-MM-DD) oder null. "
          "Setze null wenn nicht vorhanden. Nur JSON."
      )

      try:
          msg = client.messages.create(
              model=MODEL,
              max_tokens=512,
              system=system_prompt,
              messages=[{"role": "user", "content": content_parts}],
          )
          raw = msg.content[0].text.strip().replace("```json", "").replace("```", "").strip()
          return json.loads(raw)
      except Exception:
          return {}
  ```

  Note: `issued_date` is added to the extraction schema here (needed by Revue AVS A freshness check).

- [ ] **Step 5: Update user_app.py — imports and _init_session**

  In `prototype/ui/user_app.py`, make exactly three changes:

  **5a. Add import** (after the existing `from llm.email_agent import ...` block, around line 50):
  ```python
  from ui.hv_utils import extract_doc_info as _extract_doc_info
  ```

  **5b. Delete lines 948–1065** (the entire `_extract_doc_info` function body in user_app.py — it is now in hv_utils.py). The function call at line 1696 stays as-is since the alias preserves the name.

  **5c. Add new keys to `_init_session` defaults dict** (after the `"case_id"` line):
  ```python
  # HelveVista 2.0 additions
  "selected_option":        None,    # "A" | "B" | "C" | "D"
  "profile_complete":       False,
  "profile_data":           {},
  "chat_open":              False,
  "chat_messages_global":   [],
  "option_statuses":        {},      # {scenario: {option: status_str}}
  ```

- [ ] **Step 6: Run tests to verify they pass**

  ```bash
  cd prototype && python -m pytest tests/test_helvevista_2.py -v
  ```
  Expected: `PASSED test_extract_doc_info_empty_list_returns_empty_dict`

  Also verify existing tests still pass:
  ```bash
  cd prototype && python -m pytest tests/test_stellenwechsel.py -v
  ```
  Expected: all 3 scenarios PASSED.

- [ ] **Step 7: Commit**

  ```bash
  git add prototype/ui/hv_styles.py prototype/ui/hv_utils.py \
          prototype/tests/test_helvevista_2.py prototype/ui/user_app.py
  git commit -m "feat(2.0): shared foundation — hv_styles, hv_utils, session state keys"
  ```

---

## Task 2: Scenario dashboard — hv_dashboard.py

**Files:**
- Create: `prototype/ui/hv_dashboard.py`

- [ ] **Step 1: Write the failing test**

  Add to `prototype/tests/test_helvevista_2.py`:

  ```python
  from ui.hv_dashboard import SCENARIO_CARDS


  def test_scenario_cards_have_required_keys():
      required = {"id", "title", "description", "actors", "active"}
      for card in SCENARIO_CARDS:
          assert required.issubset(card.keys()), f"Missing keys in card: {card}"


  def test_active_scenarios_are_stellenwechsel_and_revue_avs():
      active_ids = {c["id"] for c in SCENARIO_CARDS if c["active"]}
      assert active_ids == {"stellenwechsel", "revue_avs"}
  ```

- [ ] **Step 2: Run to verify they fail**

  ```bash
  cd prototype && python -m pytest tests/test_helvevista_2.py::test_scenario_cards_have_required_keys -v
  ```
  Expected: `ImportError` for `ui.hv_dashboard`.

- [ ] **Step 3: Create hv_dashboard.py**

  Create `prototype/ui/hv_dashboard.py`:

  ```python
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
  ```

- [ ] **Step 4: Run tests to verify they pass**

  ```bash
  cd prototype && python -m pytest tests/test_helvevista_2.py -v
  ```
  Expected: all tests PASSED.

- [ ] **Step 5: Commit**

  ```bash
  git add prototype/ui/hv_dashboard.py prototype/tests/test_helvevista_2.py
  git commit -m "feat(2.0): scenario dashboard page"
  ```

---

## Task 3: Option cards + full main() routing

**Files:**
- Create: `prototype/ui/hv_option_cards.py`
- Create: `prototype/ui/hv_options/__init__.py`
- Modify: `prototype/ui/user_app.py` (imports + rewrite main())

- [ ] **Step 1: Write the failing tests**

  Add to `prototype/tests/test_helvevista_2.py`:

  ```python
  from ui.hv_option_cards import get_status_badge, get_option_config


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
  ```

- [ ] **Step 2: Run to verify they fail**

  ```bash
  cd prototype && python -m pytest tests/test_helvevista_2.py -v
  ```
  Expected: `ImportError` for `ui.hv_option_cards`.

- [ ] **Step 3: Create hv_options/__init__.py**

  Create `prototype/ui/hv_options/__init__.py` (empty):
  ```python
  ```

- [ ] **Step 4: Create hv_option_cards.py**

  Create `prototype/ui/hv_option_cards.py`:

  ```python
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
  ```

- [ ] **Step 5: Rewrite main() in user_app.py**

  Replace the current `main()` function (lines 4826–4865) with:

  ```python
  def main() -> None:
      import ui.hv_chat as hv_chat
      import ui.hv_dashboard as hv_dashboard
      import ui.hv_option_cards as hv_option_cards
      import ui.hv_profile as hv_profile
      import ui.hv_options.stellenwechsel_a as sw_a
      import ui.hv_options.stellenwechsel_c as sw_c
      import ui.hv_options.stellenwechsel_d as sw_d
      import ui.hv_options.revue_avs_a as avs_a
      import ui.hv_options.revue_avs_c as avs_c
      import ui.hv_options.revue_avs_d as avs_d
      # revue_avs_b is not imported: option B for both scenarios routes to the existing
      # _vs_step_* flow directly — revue_avs_b.py exists for spec completeness only.

      hv_chat.inject()
      _inject_css()

      if not st.session_state.onboarding_done:
          _show_onboarding()
          return

      if not st.session_state.logged_in:
          _page_login()
          return

      if not st.session_state.profile_complete:
          hv_profile.render()
          return

      if not st.session_state.selected_scenario:
          hv_dashboard.render()
          return

      if not st.session_state.selected_option:
          hv_option_cards.render(st.session_state.selected_scenario)
          return

      scenario = st.session_state.selected_scenario
      option   = st.session_state.selected_option
      role     = st.session_state.role

      if role == "institution":
          view = st.session_state.inst_view
          if   view == "dashboard": _inst_dashboard()
          elif view == "form":      _inst_form()
          elif view == "done":      _inst_done()
          return

      profile = st.session_state.profile_data
      case    = _load_case() or st.session_state.case

      if scenario == "stellenwechsel":
          if option == "B":
              if st.session_state.vs_step <= 1 and st.session_state.user_email:
                  _case_dashboard()
              _render_sidebar()
              step = st.session_state.vs_step
              if   step == 1: _vs_step_1_situation()
              elif step == 2: _vs_step_2_analyse()
              elif step == 3: _vs_step_3_akteure()
              elif step == 4: _vs_step_4_koordination()
              elif step == 5: _vs_step_5_ergebnis()
              elif step == 6: _vs_step_6_entscheid()
              elif step == 7: _vs_step_final()
          elif option == "A": sw_a.render(profile, case)
          elif option == "C": sw_c.render(profile, case)
          elif option == "D": sw_d.render(profile, case)
      elif scenario == "revue_avs":
          if option == "B":
              if st.session_state.vs_step <= 1 and st.session_state.user_email:
                  _case_dashboard()
              _render_sidebar()
              step = st.session_state.vs_step
              if   step == 1: _vs_step_1_situation()
              elif step == 2: _vs_step_2_analyse()
              elif step == 3: _vs_step_3_akteure()
              elif step == 4: _vs_step_4_koordination()
              elif step == 5: _vs_step_5_ergebnis()
              elif step == 6: _vs_step_6_entscheid()
              elif step == 7: _vs_step_final()
          elif option == "A": avs_a.render(profile, case)
          elif option == "C": avs_c.render(profile, case)
          elif option == "D": avs_d.render(profile, case)
  ```

  Note: imports are inside main() to defer loading until the modules exist.

- [ ] **Step 6: Run all tests**

  ```bash
  cd prototype && python -m pytest tests/ -v
  ```
  Expected: all tests PASSED (including existing test_stellenwechsel.py).

- [ ] **Step 7: Commit**

  ```bash
  git add prototype/ui/hv_option_cards.py prototype/ui/hv_options/__init__.py \
          prototype/ui/user_app.py prototype/tests/test_helvevista_2.py
  git commit -m "feat(2.0): option cards + full main() routing"
  ```

---

## Task 4: Floating chat — hv_chat.py

**Files:**
- Create: `prototype/ui/hv_chat.py`

- [ ] **Step 1: Write the failing test**

  Add to `prototype/tests/test_helvevista_2.py`:

  ```python
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
  ```

- [ ] **Step 2: Run to verify they fail**

  ```bash
  cd prototype && python -m pytest tests/test_helvevista_2.py -v
  ```
  Expected: `ImportError` for `ui.hv_chat`.

- [ ] **Step 3: Create hv_chat.py**

  Create `prototype/ui/hv_chat.py`:

  ```python
  """
  ui/hv_chat.py
  -------------
  Persistent floating chat assistant for HelveVista 2.0.
  inject() is called at the top of main() to render the panel CSS and toggle.
  The chat input is rendered at the bottom of main() when chat_open=True.
  """
  from __future__ import annotations
  import os
  import streamlit as st
  import anthropic
  from ui.hv_styles import HV_DARK, HV_CARD, HV_BORDER, HV_GOLD, HV_MUTED, HV_TEXT

  MODEL = "claude-sonnet-4-20250514"

  _OPENING_MSG = (
      "Guten Tag! Ich bin HelveVista, Ihr persönlicher Vorsorge-Assistent. "
      "Wie kann ich Ihnen helfen?"
  )


  def build_chat_context(
      scenario: str | None,
      option: str | None,
      vs_step: int,
      profile: dict,
      actor_states: dict,
  ) -> dict:
      """Return a context dict injected into every chat system prompt."""
      return {
          "scenario":     scenario or "—",
          "option":       option or "—",
          "vs_step":      vs_step,
          "vorname":      profile.get("vorname", "—"),
          "anstellung":   profile.get("anstellung", "—"),
          "actor_states": actor_states or {},
      }


  def _system_prompt(ctx: dict) -> str:
      return (
          "Du bist HelveVista, ein Vorsorge-Assistent für das Schweizer 3-Säulen-System. "
          "Du eduzierts und verbindest — du rechnest niemals Beträge aus. "
          "Antworte immer auf Deutsch, präzise und freundlich.\n\n"
          f"Aktueller Kontext:\n"
          f"- Szenario: {ctx['scenario']}\n"
          f"- Option: {ctx['option']}\n"
          f"- Schritt (falls Option B aktiv): {ctx['vs_step']}\n"
          f"- Nutzer: {ctx['vorname']}, {ctx['anstellung']}\n"
          f"- Akteure: {ctx['actor_states']}\n"
      )


  def inject() -> None:
      """
      Inject the floating chat panel CSS and toggle button.
      Must be called at the very top of main(), before any page content.
      When chat_open=True, call render_panel() at the bottom of main().
      """
      if "chat_messages_global" not in st.session_state:
          st.session_state.chat_messages_global = []
      if "chat_open" not in st.session_state:
          st.session_state.chat_open = False

      # Auto-open on first visit to dashboard or option picker (before option selected)
      if (st.session_state.get("logged_in")
              and not st.session_state.get("_chat_auto_opened")
              and not st.session_state.get("selected_option")):
          st.session_state.chat_open = True
          st.session_state["_chat_auto_opened"] = True

      # Inject CSS for the fixed-position toggle button
      st.markdown(
          f"""
  <style>
  /* Floating chat toggle pill */
  div[data-testid="stVerticalBlock"]:has(button#chat-toggle-btn) {{
      position: fixed !important;
      bottom: 22px !important;
      right: 22px !important;
      z-index: 9999 !important;
      width: auto !important;
  }}
  button#chat-toggle-btn {{
      background: {HV_GOLD} !important;
      color: {HV_DARK} !important;
      border-radius: 24px !important;
      font-weight: 700 !important;
      padding: 0.5rem 1.2rem !important;
      border: none !important;
      box-shadow: 0 4px 16px rgba(0,0,0,0.4) !important;
  }}
  </style>
          """,
          unsafe_allow_html=True,
      )

      if not st.session_state.chat_open:
          if st.button("💬 Chat", key="chat-toggle-btn"):
              st.session_state.chat_open = True
              st.rerun()


  def render_panel() -> None:
      """
      Render the chat panel. Call this at the bottom of main() when chat_open=True.
      Builds context from session state and makes LLM call on new user input.
      """
      if not st.session_state.chat_messages_global:
          st.session_state.chat_messages_global.append(
              {"role": "assistant", "content": _OPENING_MSG}
          )

      st.markdown("<hr style='border-color:#1A3048;margin:2rem 0 1rem;'/>",
                  unsafe_allow_html=True)
      st.markdown(
          f'<div style="display:flex;align-items:center;justify-content:space-between;'
          f'margin-bottom:.75rem;">'
          f'<span style="color:{HV_GOLD};font-weight:600;">💬 HelveVista Chat</span>'
          f'</div>',
          unsafe_allow_html=True,
      )

      if st.button("✕ Schliessen", key="chat-close-btn"):
          st.session_state.chat_open = False
          st.rerun()

      for msg in st.session_state.chat_messages_global[-12:]:
          with st.chat_message(msg["role"]):
              st.markdown(msg["content"], unsafe_allow_html=True)

      user_input = st.chat_input("Ihre Frage…", key="chat_global_input")
      if user_input:
          st.session_state.chat_messages_global.append(
              {"role": "user", "content": user_input}
          )
          ctx = build_chat_context(
              scenario=st.session_state.get("selected_scenario"),
              option=st.session_state.get("selected_option"),
              vs_step=st.session_state.get("vs_step", 1),
              profile=st.session_state.get("profile_data", {}),
              actor_states=st.session_state.get("case", {}).get("actor_states", {}),
          )
          answer = _llm_answer(user_input, ctx)
          st.session_state.chat_messages_global.append(
              {"role": "assistant", "content": answer}
          )
          st.rerun()


  def _llm_answer(question: str, ctx: dict) -> str:
      api_key = os.environ.get("ANTHROPIC_API_KEY")
      if not api_key:
          return "LLM nicht verfügbar (ANTHROPIC_API_KEY fehlt)."
      try:
          client = anthropic.Anthropic(api_key=api_key)
          history = st.session_state.chat_messages_global[-10:]
          messages = [{"role": m["role"], "content": m["content"]} for m in history]
          messages.append({"role": "user", "content": question})
          resp = client.messages.create(
              model=MODEL,
              max_tokens=512,
              system=_system_prompt(ctx),
              messages=messages,
          )
          return resp.content[0].text.strip()
      except Exception as e:
          return f"Fehler beim LLM-Aufruf: {e}"
  ```

- [ ] **Step 4: Wire render_panel() into main()**

  In `prototype/ui/user_app.py`, add `render_panel` call at the very end of `main()`, just before the closing of the function. Add it after all the dispatch branches (at the same indentation level as the `if scenario == ...` blocks):

  ```python
      # Floating chat panel (rendered when open, after all page content)
      if st.session_state.get("chat_open"):
          hv_chat.render_panel()
  ```

- [ ] **Step 5: Run tests**

  ```bash
  cd prototype && python -m pytest tests/ -v
  ```
  Expected: all tests PASSED.

- [ ] **Step 6: Commit**

  ```bash
  git add prototype/ui/hv_chat.py prototype/ui/user_app.py \
          prototype/tests/test_helvevista_2.py
  git commit -m "feat(2.0): floating chat panel with context injection"
  ```

---

## Task 5: Universal profile — hv_profile.py

**Files:**
- Create: `prototype/ui/hv_profile.py`

- [ ] **Step 1: Write the failing test**

  Add to `prototype/tests/test_helvevista_2.py`:

  ```python
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
  ```

- [ ] **Step 2: Run to verify they fail**

  ```bash
  cd prototype && python -m pytest tests/test_helvevista_2.py -v
  ```
  Expected: `ImportError` for `ui.hv_profile`.

- [ ] **Step 3: Create hv_profile.py**

  Create `prototype/ui/hv_profile.py`:

  ```python
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
  ```

- [ ] **Step 4: Run tests**

  ```bash
  cd prototype && python -m pytest tests/ -v
  ```
  Expected: all tests PASSED.

- [ ] **Step 5: Commit**

  ```bash
  git add prototype/ui/hv_profile.py prototype/tests/test_helvevista_2.py
  git commit -m "feat(2.0): universal user profile with MongoDB persistence"
  ```

---

## Task 6: Stellenwechsel A — Dokumente verstehen

**Files:**
- Create: `prototype/ui/hv_options/stellenwechsel_a.py`

- [ ] **Step 1: Write the failing test**

  Add to `prototype/tests/test_helvevista_2.py`:

  ```python
  from ui.hv_options.stellenwechsel_a import EXPLAINED_FIELDS


  def test_stellenwechsel_a_explains_all_four_fields():
      assert set(EXPLAINED_FIELDS) == {
          "freizuegigkeit", "koordinationsabzug", "deckungsgrad", "umwandlungssatz"
      }
  ```

- [ ] **Step 2: Run to verify it fails**

  ```bash
  cd prototype && python -m pytest tests/test_helvevista_2.py::test_stellenwechsel_a_explains_all_four_fields -v
  ```
  Expected: `ImportError`.

- [ ] **Step 3: Create stellenwechsel_a.py**

  Create `prototype/ui/hv_options/stellenwechsel_a.py`:

  ```python
  """
  hv_options/stellenwechsel_a.py
  -------------------------------
  Option A — Dokumente verstehen (Stellenwechsel).
  User uploads Vorsorgeausweis; HelveVista explains 4 key fields in plain German.
  Educational only — no institution contact, no state machine.
  """
  from __future__ import annotations
  import os
  import json
  import streamlit as st
  import anthropic
  from ui.hv_utils import extract_doc_info
  from ui.hv_styles import HV_GOLD, HV_MUTED, HV_BORDER, HV_CARD

  MODEL = "claude-sonnet-4-20250514"

  EXPLAINED_FIELDS = ("freizuegigkeit", "koordinationsabzug", "deckungsgrad", "umwandlungssatz")

  _FIELD_LABELS = {
      "freizuegigkeit":    "Freizügigkeitsguthaben",
      "koordinationsabzug": "Koordinationsabzug",
      "deckungsgrad":      "Deckungsgrad",
      "umwandlungssatz":   "Umwandlungssatz",
  }

  _SYSTEM_PROMPT = (
      "Du bist HelveVista, ein Bildungsassistent für das Schweizer BVG-System. "
      "Du erhältst Daten aus einem Vorsorgeausweis. "
      "Erkläre die folgenden vier Felder in einfachem Deutsch — klar, ohne Fachjargon, "
      "ohne Berechnungen, in je 2-3 Sätzen:\n"
      "- Freizügigkeitsguthaben (freizuegigkeit)\n"
      "- Koordinationsabzug (koordinationsabzug)\n"
      "- Deckungsgrad (deckungsgrad)\n"
      "- Umwandlungssatz (umwandlungssatz)\n\n"
      "Antworte NUR mit JSON:\n"
      '{"freizuegigkeit":"...","koordinationsabzug":"...","deckungsgrad":"...","umwandlungssatz":"..."}\n'
      "Wenn ein Wert im Dokument fehlt, erkläre den Begriff trotzdem allgemein."
  )


  def _explain_fields(extracted: dict) -> dict[str, str]:
      """Call LLM to explain the 4 fields. Returns {field: explanation} or {}."""
      api_key = os.environ.get("ANTHROPIC_API_KEY")
      if not api_key:
          return {}
      try:
          client = anthropic.Anthropic(api_key=api_key)
          context = json.dumps({k: extracted.get(k) for k in (
              "freizuegigkeit_chf", "koordinationsabzug_chf",
              "pensionskasse", "arbeitgeber",
          )}, ensure_ascii=False)
          resp = client.messages.create(
              model=MODEL,
              max_tokens=800,
              system=_SYSTEM_PROMPT,
              messages=[{"role": "user", "content": f"Dokumentdaten: {context}"}],
          )
          raw = resp.content[0].text.strip().replace("```json", "").replace("```", "")
          return json.loads(raw)
      except Exception:
          return {}


  def render(profile: dict, case: dict) -> None:
      scenario = st.session_state.get("selected_scenario", "stellenwechsel")

      st.markdown(
          f'<h2 style="margin-bottom:.25rem;">Dokumente verstehen</h2>'
          f'<p style="color:{HV_MUTED};font-size:.88rem;margin-bottom:1.5rem;">'
          f"Laden Sie Ihren Vorsorgeausweis hoch. HelveVista erklärt jeden Abschnitt.</p>",
          unsafe_allow_html=True,
      )

      if st.button("← Zurück zur Optionswahl", key="sw_a_back"):
          st.session_state.selected_option = None
          st.rerun()

      uploaded = st.file_uploader(
          "Vorsorgeausweis hochladen (PDF, PNG, JPG)",
          type=["pdf", "png", "jpg", "jpeg"],
          key="sw_a_upload",
          accept_multiple_files=True,
      )

      if not uploaded:
          st.info("Bitte laden Sie Ihren Vorsorgeausweis hoch, um fortzufahren.")
          return

      state_key = "sw_a_explanations"
      if state_key not in st.session_state or st.button("Neu analysieren", key="sw_a_reanalyse"):
          with st.spinner("Dokument wird analysiert…"):
              extracted = extract_doc_info(list(uploaded))
              explanations = _explain_fields(extracted)
          st.session_state[state_key] = explanations
          st.session_state["extracted_doc_data"] = extracted
          # Advance option status
          st.session_state.option_statuses.setdefault(scenario, {})["A"] = "geklaert"

      explanations: dict = st.session_state.get(state_key, {})

      if not explanations:
          st.warning("Erklärungen konnten nicht geladen werden. Bitte versuchen Sie es erneut.")
          return

      st.markdown(
          f'<p style="color:{HV_GOLD};font-size:.8rem;letter-spacing:.1em;margin:1rem 0 .5rem;">'
          f"ERKLÄRUNGEN AUS IHREM VORSORGEAUSWEIS</p>",
          unsafe_allow_html=True,
      )

      for field in EXPLAINED_FIELDS:
          label = _FIELD_LABELS[field]
          text  = explanations.get(field, "—")
          with st.expander(label, expanded=True):
              st.markdown(
                  f'<p style="color:#C8D8E8;font-size:.88rem;line-height:1.7;">{text}</p>',
                  unsafe_allow_html=True,
              )

      st.success("✅ Ihre Dokumente wurden erklärt. Status: Geklärt.")
  ```

- [ ] **Step 4: Run tests**

  ```bash
  cd prototype && python -m pytest tests/ -v
  ```
  Expected: all tests PASSED.

- [ ] **Step 5: Commit**

  ```bash
  git add prototype/ui/hv_options/stellenwechsel_a.py prototype/tests/test_helvevista_2.py
  git commit -m "feat(2.0): Stellenwechsel A — Dokumente verstehen"
  ```

---

## Task 7: Stellenwechsel C — Diagnostic chat

**Files:**
- Create: `prototype/ui/hv_options/stellenwechsel_c.py`

- [ ] **Step 1: Write the failing test**

  Add to `prototype/tests/test_helvevista_2.py`:

  ```python
  from ui.hv_options.stellenwechsel_c import parse_recommendation


  def test_parse_recommendation_detects_option_B():
      text = "Ich empfehle Ihnen Option B, da Sie bereits einen Arbeitgeberwechsel vollzogen haben.\n\nEMPFEHLUNG: B"
      assert parse_recommendation(text) == "B"


  def test_parse_recommendation_returns_none_when_absent():
      text = "Können Sie mir mehr über Ihre Situation erzählen?"
      assert parse_recommendation(text) is None


  def test_parse_recommendation_case_insensitive():
      assert parse_recommendation("EMPFEHLUNG: a") == "A"
  ```

- [ ] **Step 2: Run to verify they fail**

  ```bash
  cd prototype && python -m pytest tests/test_helvevista_2.py -k "parse_recommendation" -v
  ```
  Expected: `ImportError`.

- [ ] **Step 3: Create stellenwechsel_c.py**

  Create `prototype/ui/hv_options/stellenwechsel_c.py`:

  ```python
  """
  hv_options/stellenwechsel_c.py
  -------------------------------
  Option C — Ich weiss nicht wo anfangen (Stellenwechsel).
  Free-form diagnostic chat. Recommends Option A, B, or D.
  """
  from __future__ import annotations
  import os
  import re
  import streamlit as st
  import anthropic
  from ui.hv_styles import HV_GOLD, HV_MUTED

  MODEL = "claude-sonnet-4-20250514"

  _SYSTEM_PROMPT = (
      "Du bist HelveVista, ein Vorsorge-Assistent. "
      "Der Nutzer weiss nicht, wo er im Bereich Stellenwechsel anfangen soll. "
      "Stelle gezielte Fragen zur Situation (maximal 2 auf einmal). "
      "Wenn du genug weisst, empfehle EXAKT EINE der folgenden Optionen:\n"
      "- Option A: Dokumente verstehen (Nutzer möchte seinen Vorsorgeausweis verstehen)\n"
      "- Option B: Démarches starten (Nutzer hat Job gewechselt und muss koordinieren)\n"
      "- Option D: LPP-Einkauf verstehen (Nutzer interessiert sich für steuerliche Optimierung)\n\n"
      "Antworte immer auf Deutsch. "
      "Empfehle nie mehrere Optionen gleichzeitig. "
      "Wenn du eine Empfehlung gibst, füge am Ende einen neuen Absatz mit genau diesem Format ein:\n"
      "EMPFEHLUNG: [A|B|D]"
  )

  _OPENING = (
      "Guten Tag! Ich helfe Ihnen, den richtigen Weg im Bereich Stellenwechsel zu finden. "
      "Können Sie mir kurz schildern, was Sie beschäftigt?"
  )


  def parse_recommendation(text: str) -> str | None:
      """
      Extract 'EMPFEHLUNG: X' from LLM response text.
      Returns the letter ('A', 'B', or 'D') or None if not present.
      """
      match = re.search(r"EMPFEHLUNG:\s*([ABDabd])", text)
      return match.group(1).upper() if match else None


  def render(profile: dict, case: dict) -> None:
      scenario = st.session_state.get("selected_scenario", "stellenwechsel")

      st.markdown(
          f'<h2 style="margin-bottom:.25rem;">Wo anfangen?</h2>'
          f'<p style="color:{HV_MUTED};font-size:.88rem;margin-bottom:1.5rem;">'
          f"Beschreiben Sie Ihre Situation. HelveVista analysiert und empfiehlt den richtigen Weg.</p>",
          unsafe_allow_html=True,
      )

      if st.button("← Zurück zur Optionswahl", key="sw_c_back"):
          st.session_state.selected_option = None
          st.rerun()

      msgs_key = "sw_c_messages"
      if msgs_key not in st.session_state:
          st.session_state[msgs_key] = [{"role": "assistant", "content": _OPENING}]

      for msg in st.session_state[msgs_key]:
          with st.chat_message(msg["role"]):
              st.markdown(msg["content"], unsafe_allow_html=True)

      # Render jump button if last assistant message contains a recommendation
      last_assistant = next(
          (m["content"] for m in reversed(st.session_state[msgs_key])
           if m["role"] == "assistant"), ""
      )
      rec = parse_recommendation(last_assistant)
      if rec:
          if st.button(f"Option {rec} starten →", key=f"sw_c_jump_{rec}", type="primary"):
              st.session_state.selected_option = rec
              st.session_state.option_statuses.setdefault(scenario, {})[rec] = "in_bearbeitung"
              st.rerun()

      user_input = st.chat_input("Ihre Situation…", key="sw_c_input")
      if user_input:
          st.session_state[msgs_key].append({"role": "user", "content": user_input})
          reply = _llm_reply(st.session_state[msgs_key])
          st.session_state[msgs_key].append({"role": "assistant", "content": reply})
          st.session_state.option_statuses.setdefault(scenario, {}).setdefault("C", "in_bearbeitung")
          st.rerun()


  def _llm_reply(messages: list[dict]) -> str:
      api_key = os.environ.get("ANTHROPIC_API_KEY")
      if not api_key:
          return "LLM nicht verfügbar (ANTHROPIC_API_KEY fehlt)."
      try:
          client = anthropic.Anthropic(api_key=api_key)
          resp = client.messages.create(
              model=MODEL,
              max_tokens=512,
              system=_SYSTEM_PROMPT,
              messages=[{"role": m["role"], "content": m["content"]} for m in messages[-12:]],
          )
          return resp.content[0].text.strip()
      except Exception as e:
          return f"Fehler: {e}"
  ```

- [ ] **Step 4: Run tests**

  ```bash
  cd prototype && python -m pytest tests/ -v
  ```
  Expected: all tests PASSED.

- [ ] **Step 5: Commit**

  ```bash
  git add prototype/ui/hv_options/stellenwechsel_c.py prototype/tests/test_helvevista_2.py
  git commit -m "feat(2.0): Stellenwechsel C — diagnostic chat with option recommendation"
  ```

---

## Task 8: Stellenwechsel D — LPP-Einkauf verstehen

**Files:**
- Create: `prototype/ui/hv_options/stellenwechsel_d.py`

- [ ] **Step 1: Write the failing test**

  Add to `prototype/tests/test_helvevista_2.py`:

  ```python
  from ui.hv_options.stellenwechsel_d import LPP_SECTIONS


  def test_lpp_sections_has_four_entries():
      assert len(LPP_SECTIONS) == 4


  def test_lpp_sections_have_title_and_content():
      for s in LPP_SECTIONS:
          assert "title" in s and "content" in s
          assert len(s["content"]) > 20
  ```

- [ ] **Step 2: Run to verify they fail**

  ```bash
  cd prototype && python -m pytest tests/test_helvevista_2.py -k "lpp" -v
  ```
  Expected: `ImportError`.

- [ ] **Step 3: Create stellenwechsel_d.py**

  Create `prototype/ui/hv_options/stellenwechsel_d.py`:

  ```python
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
      import uuid, time

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
          # Build minimal case dict for email agent
          minimal_case = {
              "case_id":   case.get("case_id") or uuid.uuid4().hex[:8].upper(),
              "user_name": st.session_state.get("user_name", ""),
              "user_email": st.session_state.get("user_email", ""),
              "situation": "LPP-Einkauf: Anfrage für persönliches Einkaufszertifikat.",
              "verfahren": "LPP-Einkauf",
          }
          with st.spinner("E-Mail wird gesendet…"):
              ok = send_institution_email(Actor.NEW_PK, minimal_case, email_input.strip())
          if ok:
              st.session_state.option_statuses.setdefault(scenario, {})["D"] = "anfrage_gesendet"
              st.success("✅ Ihre Anfrage wurde an die Pensionskasse gesendet.")
              st.rerun()
          else:
              st.error("Fehler beim Senden. Bitte prüfen Sie die E-Mail-Adresse.")
  ```

- [ ] **Step 4: Run tests**

  ```bash
  cd prototype && python -m pytest tests/ -v
  ```
  Expected: all tests PASSED.

- [ ] **Step 5: Commit**

  ```bash
  git add prototype/ui/hv_options/stellenwechsel_d.py prototype/tests/test_helvevista_2.py
  git commit -m "feat(2.0): Stellenwechsel D — LPP-Einkauf education + PK certificate request"
  ```

---

## Task 9: Revue AVS A — IK-Auszug verstehen

**Files:**
- Create: `prototype/ui/hv_options/revue_avs_a.py`

- [ ] **Step 1: Write the failing test**

  Add to `prototype/tests/test_helvevista_2.py`:

  ```python
  from ui.hv_options.revue_avs_a import is_ik_stale
  from datetime import date


  def test_is_ik_stale_returns_true_for_date_over_12_months_ago():
      old_date = date(2024, 1, 1).isoformat()  # clearly > 12 months before 2026-04-20
      assert is_ik_stale(old_date) is True


  def test_is_ik_stale_returns_false_for_recent_date():
      recent = date(2026, 1, 15).isoformat()   # < 12 months before 2026-04-20
      assert is_ik_stale(recent) is False


  def test_is_ik_stale_returns_false_for_none():
      assert is_ik_stale(None) is False


  def test_is_ik_stale_returns_false_for_unparseable_string():
      assert is_ik_stale("not-a-date") is False
  ```

- [ ] **Step 2: Run to verify they fail**

  ```bash
  cd prototype && python -m pytest tests/test_helvevista_2.py -k "ik_stale" -v
  ```
  Expected: `ImportError`.

- [ ] **Step 3: Create revue_avs_a.py**

  Create `prototype/ui/hv_options/revue_avs_a.py`:

  ```python
  """
  hv_options/revue_avs_a.py
  --------------------------
  Option A — IK-Auszug verstehen (Revue AVS).
  User uploads AHV individual account statement; HelveVista explains it.
  Freshness check: warns if document is older than 12 months.
  """
  from __future__ import annotations
  import os
  import json
  from datetime import date, datetime
  import streamlit as st
  import anthropic
  from ui.hv_utils import extract_doc_info
  from ui.hv_styles import HV_GOLD, HV_MUTED

  MODEL = "claude-sonnet-4-20250514"

  _SYSTEM_PROMPT = (
      "Du bist HelveVista, ein Bildungsassistent für das Schweizer AHV-System. "
      "Du erhältst Daten aus einem IK-Auszug (Individuelle Kontenauszug). "
      "Erkläre folgende Aspekte in einfachem Deutsch, ohne Berechnungen:\n"
      "1. Beitragsjahre: Was sie bedeuten und warum sie wichtig sind\n"
      "2. Lücken: Was eine Beitragslücke ist und welche Konsequenzen sie hat\n"
      "3. Freiwillige Nachzahlungen: Ob und wann eine Nachzahlung sinnvoll sein kann\n\n"
      "Antworte NUR mit JSON:\n"
      '{"beitragsjahre":"...","luecken":"...","nachzahlungen":"..."}\n'
      "Wenn Daten fehlen, erkläre die Begriffe allgemein. Nur JSON."
  )


  def is_ik_stale(issued_date_str: str | None, months: int = 12) -> bool:
      """
      Return True if issued_date_str is more than `months` months in the past.
      Returns False for None, empty string, or unparseable dates.
      """
      if not issued_date_str:
          return False
      try:
          issued = date.fromisoformat(str(issued_date_str)[:10])
          today  = date.today()
          delta  = (today.year - issued.year) * 12 + (today.month - issued.month)
          return delta > months
      except (ValueError, TypeError):
          return False


  def _explain_ik(extracted: dict) -> dict[str, str]:
      api_key = os.environ.get("ANTHROPIC_API_KEY")
      if not api_key:
          return {}
      try:
          client = anthropic.Anthropic(api_key=api_key)
          context = json.dumps({
              "beitragsjahre": extracted.get("beitragsjahre"),
              "luecken":       extracted.get("luecken"),
              "issued_date":   extracted.get("issued_date"),
          }, ensure_ascii=False)
          resp = client.messages.create(
              model=MODEL,
              max_tokens=600,
              system=_SYSTEM_PROMPT,
              messages=[{"role": "user", "content": f"IK-Auszug Daten: {context}"}],
          )
          raw = resp.content[0].text.strip().replace("```json", "").replace("```", "")
          return json.loads(raw)
      except Exception:
          return {}


  def render(profile: dict, case: dict) -> None:
      scenario = st.session_state.get("selected_scenario", "revue_avs")

      st.markdown(
          f'<h2 style="margin-bottom:.25rem;">IK-Auszug verstehen</h2>'
          f'<p style="color:{HV_MUTED};font-size:.88rem;margin-bottom:1.5rem;">'
          f"Laden Sie Ihren IK-Auszug hoch. HelveVista erklärt Beitragsjahre und Lücken.</p>",
          unsafe_allow_html=True,
      )

      if st.button("← Zurück zur Optionswahl", key="avs_a_back"):
          st.session_state.selected_option = None
          st.rerun()

      uploaded = st.file_uploader(
          "IK-Auszug hochladen (PDF, PNG, JPG)",
          type=["pdf", "png", "jpg", "jpeg"],
          key="avs_a_upload",
          accept_multiple_files=True,
      )

      if not uploaded:
          st.info("Bitte laden Sie Ihren IK-Auszug (Individuelle Kontenauszug) hoch.")
          return

      state_key = "avs_a_explanations"
      if state_key not in st.session_state or st.button("Neu analysieren", key="avs_a_reanalyse"):
          with st.spinner("IK-Auszug wird analysiert…"):
              extracted = extract_doc_info(list(uploaded))
              explanations = _explain_ik(extracted)
          st.session_state[state_key] = explanations
          st.session_state["avs_a_extracted"] = extracted
          st.session_state.option_statuses.setdefault(scenario, {})["A"] = "geklaert"

      extracted = st.session_state.get("avs_a_extracted", {})
      explanations: dict = st.session_state.get(state_key, {})

      # Freshness warning
      if is_ik_stale(extracted.get("issued_date")):
          st.warning(
              "⚠️ Dieser IK-Auszug wurde vor mehr als 12 Monaten ausgestellt "
              "und ist möglicherweise nicht mehr aktuell. "
              "Beantragen Sie einen neuen Auszug unter ch.ch/ik-auszug."
          )

      if not explanations:
          st.warning("Erklärungen konnten nicht geladen werden. Bitte versuchen Sie es erneut.")
          return

      _LABELS = {
          "beitragsjahre": "Beitragsjahre",
          "luecken":       "Beitragslücken",
          "nachzahlungen": "Freiwillige Nachzahlungen",
      }

      st.markdown(
          f'<p style="color:{HV_GOLD};font-size:.8rem;letter-spacing:.1em;margin:1rem 0 .5rem;">'
          f"ERKLÄRUNGEN AUS IHREM IK-AUSZUG</p>",
          unsafe_allow_html=True,
      )

      for field, label in _LABELS.items():
          with st.expander(label, expanded=True):
              st.markdown(
                  f'<p style="color:#C8D8E8;font-size:.88rem;line-height:1.7;">'
                  f'{explanations.get(field, "—")}</p>',
                  unsafe_allow_html=True,
              )

      st.success("✅ Ihr IK-Auszug wurde erklärt. Status: Geklärt.")
  ```

- [ ] **Step 4: Run tests**

  ```bash
  cd prototype && python -m pytest tests/ -v
  ```
  Expected: all tests PASSED.

- [ ] **Step 5: Commit**

  ```bash
  git add prototype/ui/hv_options/revue_avs_a.py prototype/tests/test_helvevista_2.py
  git commit -m "feat(2.0): Revue AVS A — IK-Auszug verstehen with 12-month freshness check"
  ```

---

## Task 10: Revue AVS B — Anfrage stellen (thin wrapper)

**Files:**
- Create: `prototype/ui/hv_options/revue_avs_b.py`

This option delegates to the existing step flow. No new LLM calls. No test needed beyond import smoke test.

- [ ] **Step 1: Write the smoke test**

  Add to `prototype/tests/test_helvevista_2.py`:

  ```python
  import ui.hv_options.revue_avs_b  # smoke: module imports without error
  ```

- [ ] **Step 2: Create revue_avs_b.py**

  Create `prototype/ui/hv_options/revue_avs_b.py`:

  ```python
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
  ```

- [ ] **Step 3: Run tests**

  ```bash
  cd prototype && python -m pytest tests/ -v
  ```
  Expected: all tests PASSED.

- [ ] **Step 4: Commit**

  ```bash
  git add prototype/ui/hv_options/revue_avs_b.py prototype/tests/test_helvevista_2.py
  git commit -m "feat(2.0): Revue AVS B — thin wrapper for existing flow"
  ```

---

## Task 11: Revue AVS C — Diagnostic chat

**Files:**
- Create: `prototype/ui/hv_options/revue_avs_c.py`

- [ ] **Step 1: Write the failing test**

  Add to `prototype/tests/test_helvevista_2.py`:

  ```python
  from ui.hv_options.revue_avs_c import parse_recommendation as avs_parse_rec


  def test_avs_parse_recommendation_detects_option_A():
      text = "Ich empfehle Ihnen, mit Option A zu beginnen.\n\nEMPFEHLUNG: A"
      assert avs_parse_rec(text) == "A"
  ```

- [ ] **Step 2: Run to verify it fails**

  ```bash
  cd prototype && python -m pytest tests/test_helvevista_2.py::test_avs_parse_recommendation_detects_option_A -v
  ```
  Expected: `ImportError`.

- [ ] **Step 3: Create revue_avs_c.py**

  Create `prototype/ui/hv_options/revue_avs_c.py`:

  ```python
  """
  hv_options/revue_avs_c.py
  --------------------------
  Option C — Ich weiss nicht wo anfangen (Revue AVS).
  Same pattern as stellenwechsel_c but AVS-focused system prompt.
  Recommends Option A, B, or D.
  """
  from __future__ import annotations
  import os
  import re
  import streamlit as st
  import anthropic
  from ui.hv_styles import HV_MUTED

  MODEL = "claude-sonnet-4-20250514"

  _SYSTEM_PROMPT = (
      "Du bist HelveVista, ein Vorsorge-Assistent. "
      "Der Nutzer weiss nicht, wo er im Bereich AHV / Revue AVS anfangen soll. "
      "Stelle gezielte Fragen zur AHV-Situation (maximal 2 auf einmal). "
      "Wenn du genug weisst, empfehle EXAKT EINE der folgenden Optionen:\n"
      "- Option A: IK-Auszug verstehen (Nutzer möchte seinen IK-Auszug verstehen)\n"
      "- Option B: Anfrage stellen (Nutzer möchte einen aktuellen IK-Auszug bei der AHV beantragen)\n"
      "- Option D: AVS-Lücke schliessen (Nutzer hat Beitragslücken und möchte nachzahlen)\n\n"
      "Antworte immer auf Deutsch. "
      "Empfehle nie mehrere Optionen gleichzeitig. "
      "Wenn du eine Empfehlung gibst, füge am Ende einen neuen Absatz mit genau diesem Format ein:\n"
      "EMPFEHLUNG: [A|B|D]"
  )

  _OPENING = (
      "Guten Tag! Ich helfe Ihnen, den richtigen Weg im Bereich AHV / Revue AVS zu finden. "
      "Was beschäftigt Sie bezüglich Ihrer AHV-Situation?"
  )


  def parse_recommendation(text: str) -> str | None:
      match = re.search(r"EMPFEHLUNG:\s*([ABDabd])", text)
      return match.group(1).upper() if match else None


  def render(profile: dict, case: dict) -> None:
      scenario = st.session_state.get("selected_scenario", "revue_avs")

      st.markdown(
          f'<h2 style="margin-bottom:.25rem;">Wo anfangen?</h2>'
          f'<p style="color:{HV_MUTED};font-size:.88rem;margin-bottom:1.5rem;">'
          f"Beschreiben Sie Ihre AHV-Situation. HelveVista analysiert und empfiehlt den richtigen Weg.</p>",
          unsafe_allow_html=True,
      )

      if st.button("← Zurück zur Optionswahl", key="avs_c_back"):
          st.session_state.selected_option = None
          st.rerun()

      msgs_key = "avs_c_messages"
      if msgs_key not in st.session_state:
          st.session_state[msgs_key] = [{"role": "assistant", "content": _OPENING}]

      for msg in st.session_state[msgs_key]:
          with st.chat_message(msg["role"]):
              st.markdown(msg["content"], unsafe_allow_html=True)

      last_assistant = next(
          (m["content"] for m in reversed(st.session_state[msgs_key])
           if m["role"] == "assistant"), ""
      )
      rec = parse_recommendation(last_assistant)
      if rec:
          if st.button(f"Option {rec} starten →", key=f"avs_c_jump_{rec}", type="primary"):
              st.session_state.selected_option = rec
              st.session_state.option_statuses.setdefault(scenario, {})[rec] = "in_bearbeitung"
              st.rerun()

      user_input = st.chat_input("Ihre Situation…", key="avs_c_input")
      if user_input:
          st.session_state[msgs_key].append({"role": "user", "content": user_input})
          reply = _llm_reply(st.session_state[msgs_key])
          st.session_state[msgs_key].append({"role": "assistant", "content": reply})
          st.session_state.option_statuses.setdefault(scenario, {}).setdefault("C", "in_bearbeitung")
          st.rerun()


  def _llm_reply(messages: list[dict]) -> str:
      api_key = os.environ.get("ANTHROPIC_API_KEY")
      if not api_key:
          return "LLM nicht verfügbar (ANTHROPIC_API_KEY fehlt)."
      try:
          client = anthropic.Anthropic(api_key=api_key)
          resp = client.messages.create(
              model=MODEL,
              max_tokens=512,
              system=_SYSTEM_PROMPT,
              messages=[{"role": m["role"], "content": m["content"]} for m in messages[-12:]],
          )
          return resp.content[0].text.strip()
      except Exception as e:
          return f"Fehler: {e}"
  ```

- [ ] **Step 4: Run tests**

  ```bash
  cd prototype && python -m pytest tests/ -v
  ```

- [ ] **Step 5: Commit**

  ```bash
  git add prototype/ui/hv_options/revue_avs_c.py prototype/tests/test_helvevista_2.py
  git commit -m "feat(2.0): Revue AVS C — diagnostic chat with option recommendation"
  ```

---

## Task 12: Revue AVS D — AVS-Lücke schliessen

**Files:**
- Create: `prototype/ui/hv_options/revue_avs_d.py`

- [ ] **Step 1: Write the failing test**

  Add to `prototype/tests/test_helvevista_2.py`:

  ```python
  from ui.hv_options.revue_avs_d import AVS_SECTIONS


  def test_avs_sections_has_three_entries():
      assert len(AVS_SECTIONS) == 3


  def test_avs_sections_keys_are_correct():
      titles = {s["title"] for s in AVS_SECTIONS}
      assert "Wer ist betroffen" in titles
      assert "Zeitfenster" in titles
      assert "Ablauf der Nachzahlung" in titles
  ```

- [ ] **Step 2: Run to verify they fail**

  ```bash
  cd prototype && python -m pytest tests/test_helvevista_2.py -k "avs_sections" -v
  ```
  Expected: `ImportError`.

- [ ] **Step 3: Create revue_avs_d.py**

  Create `prototype/ui/hv_options/revue_avs_d.py`:

  ```python
  """
  hv_options/revue_avs_d.py
  --------------------------
  Option D — AVS-Lücke schliessen (Revue AVS).
  Educates on AHV voluntary contributions; connects to AHV-Ausgleichskasse.
  Never calculates amounts.
  """
  from __future__ import annotations
  import uuid
  import streamlit as st
  from ui.hv_styles import HV_GOLD, HV_MUTED

  AVS_SECTIONS: list[dict] = [
      {
          "title": "Wer ist betroffen",
          "content": (
              "Beitragslücken entstehen, wenn jemand in einem Jahr weniger als die Mindestbeiträge "
              "in die AHV eingezahlt hat — etwa durch Erwerbsunterbrechungen, Auslandaufenthalte, "
              "oder Phasen der Selbständigkeit ohne ausreichende Beiträge. "
              "Auch Auslandjahre vor dem 20. Lebensjahr können zu Lücken führen."
          ),
      },
      {
          "title": "Zeitfenster",
          "content": (
              "Freiwillige Nachzahlungen sind grundsätzlich für die letzten 5 Beitragsjahre möglich. "
              "Ausnahmen gelten für Personen, die sich im Ausland befunden haben: "
              "In bestimmten Fällen können ältere Lücken nachgezahlt werden. "
              "Die genauen Fristen und Möglichkeiten klären Sie direkt mit der AHV-Ausgleichskasse."
          ),
      },
      {
          "title": "Ablauf der Nachzahlung",
          "content": (
              "1. Beantragen Sie einen aktuellen IK-Auszug, um Ihre Beitragsjahre zu kennen. "
              "2. Wenden Sie sich an die zuständige AHV-Ausgleichskasse für eine Berechnung. "
              "3. Bezahlen Sie den festgelegten Nachzahlungsbetrag fristgerecht. "
              "4. Die Nachzahlung wird in Ihrer AHV-Beitragshistorie vermerkt."
          ),
      },
  ]

  _DISCLAIMER = (
      "⚠️ HelveVista berechnet keine Beträge. "
      "Die genauen Nachzahlungsbeträge und Fristen erhalten Sie von der AHV-Ausgleichskasse."
  )


  def render(profile: dict, case: dict) -> None:
      from llm.email_agent import send_institution_email
      from core.states import Actor

      scenario = st.session_state.get("selected_scenario", "revue_avs")

      st.markdown(
          f'<h2 style="margin-bottom:.25rem;">AVS-Lücke schliessen</h2>'
          f'<p style="color:{HV_MUTED};font-size:.88rem;margin-bottom:1.5rem;">'
          f"Verstehen Sie die Regeln für freiwillige Nachzahlungen.</p>",
          unsafe_allow_html=True,
      )

      if st.button("← Zurück zur Optionswahl", key="avs_d_back"):
          st.session_state.selected_option = None
          st.rerun()

      st.warning(_DISCLAIMER)

      for section in AVS_SECTIONS:
          with st.expander(section["title"], expanded=False):
              st.markdown(
                  f'<p style="color:#C8D8E8;font-size:.88rem;line-height:1.7;">{section["content"]}</p>',
                  unsafe_allow_html=True,
              )

      st.markdown("---")
      st.markdown(
          f'<p style="color:{HV_GOLD};font-size:.9rem;font-weight:600;margin-bottom:.5rem;">'
          f"Genaue Zahlen bei der AHV-Ausgleichskasse anfragen</p>"
          f'<p style="color:{HV_MUTED};font-size:.84rem;margin-bottom:1rem;">'
          f"Die AHV-Ausgleichskasse berechnet den exakten Nachzahlungsbetrag und die Fristen.</p>",
          unsafe_allow_html=True,
      )

      email_input = st.text_input("E-Mail-Adresse Ihrer AHV-Ausgleichskasse",
                                  key="avs_d_email",
                                  placeholder="info@ausgleichskasse.ch")

      status = st.session_state.option_statuses.get(scenario, {}).get("D", "in_bearbeitung")

      if status in ("anfrage_gesendet", "antwort_erhalten"):
          st.success("📤 Anfrage wurde bereits gesendet.")
      elif st.button("Anfrage senden →", key="avs_d_send", type="primary",
                     disabled=not email_input.strip()):
          minimal_case = {
              "case_id":    case.get("case_id") or uuid.uuid4().hex[:8].upper(),
              "user_name":  st.session_state.get("user_name", ""),
              "user_email": st.session_state.get("user_email", ""),
              "situation":  "AVS-Lücke: Anfrage für genaue Nachzahlungsbeträge.",
              "verfahren":  "AVS-Nachzahlung",
          }
          with st.spinner("E-Mail wird gesendet…"):
              ok = send_institution_email(Actor.AVS, minimal_case, email_input.strip())
          if ok:
              st.session_state.option_statuses.setdefault(scenario, {})["D"] = "anfrage_gesendet"
              st.success("✅ Ihre Anfrage wurde an die AHV-Ausgleichskasse gesendet.")
              st.rerun()
          else:
              st.error("Fehler beim Senden. Bitte prüfen Sie die E-Mail-Adresse.")
  ```

- [ ] **Step 4: Run tests**

  ```bash
  cd prototype && python -m pytest tests/ -v
  ```
  Expected: all tests PASSED.

- [ ] **Step 5: Commit**

  ```bash
  git add prototype/ui/hv_options/revue_avs_d.py prototype/tests/test_helvevista_2.py
  git commit -m "feat(2.0): Revue AVS D — AVS-Lücke education + AHV-Ausgleichskasse request"
  ```

---

## Task 13: Integration smoke test + final verification

**Files:**
- No new files — verify full integration runs without import errors

- [ ] **Step 1: Run the full test suite**

  ```bash
  cd prototype && python -m pytest tests/ -v
  ```
  Expected output: all tests in `test_helvevista_2.py` and `test_stellenwechsel.py` PASSED with zero failures.

- [ ] **Step 2: Verify Streamlit app starts without import errors**

  ```bash
  cd prototype && python -c "
  import sys, os
  sys.path.insert(0, '.')
  from ui import hv_styles, hv_utils, hv_profile, hv_dashboard, hv_option_cards, hv_chat
  from ui.hv_options import stellenwechsel_a, stellenwechsel_c, stellenwechsel_d
  from ui.hv_options import revue_avs_a, revue_avs_b, revue_avs_c, revue_avs_d
  print('All imports OK')
  "
  ```
  Expected: `All imports OK` with no traceback.

- [ ] **Step 3: Verify existing core tests still pass**

  ```bash
  cd prototype && python -m pytest tests/test_stellenwechsel.py -v
  ```
  Expected: H1 (Safety), H2 (Liveness), H3 (Happy Path) all PASSED — proving the core layer was not touched.

- [ ] **Step 4: Final commit**

  ```bash
  git add .
  git commit -m "feat(2.0): complete integration — all modules wired, all tests passing"
  ```

---

## Summary

| Task | Files Created | Key Behavior |
|---|---|---|
| 1 | hv_styles, hv_utils, test file | Foundation + extract_doc_info moved |
| 2 | hv_dashboard | Scenario selection page |
| 3 | hv_option_cards, hv_options/__init__ | A/B/C/D picker + full main() routing |
| 4 | hv_chat | Floating chat with context injection |
| 5 | hv_profile | Profile form + MongoDB persistence |
| 6 | stellenwechsel_a | Vorsorgeausweis explainer |
| 7 | stellenwechsel_c | Diagnostic chat → recommend A/B/D |
| 8 | stellenwechsel_d | LPP education + PK email |
| 9 | revue_avs_a | IK-Auszug explainer + freshness check |
| 10 | revue_avs_b | Thin wrapper for existing flow |
| 11 | revue_avs_c | Diagnostic chat → recommend A/B/D |
| 12 | revue_avs_d | AVS-Lücke education + AHV email |
| 13 | — | Integration smoke test |

**user_app.py is modified in Tasks 1 and 3 only.** All other tasks create new files exclusively.

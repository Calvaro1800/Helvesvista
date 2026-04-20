# HelveVista 2.0 — Design Document

**Date:** 2026-04-20  
**Author:** Christopher Alvaro  
**Status:** Approved — ready for implementation  
**Thesis:** Bachelor Thesis, ZHAW School of Management and Law

---

## 1. Scope

HelveVista 2.0 is a UX overhaul layered on top of the existing working prototype. The existing 6-step Stellenwechsel flow (Schritt 1–6 in `user_app.py`) is preserved byte-for-byte. All additions are purely UI layer — `core/` and `llm/` are not modified.

**What is added:**
- A scenario dashboard replacing the current scenario selection page
- Per-scenario option cards (A/B/C/D) with status tracking
- Six new option implementations (Stellenwechsel A/C/D, Revue AVS A/C/D)
- A universal user profile collected once at first login
- A persistent floating chat assistant, context-aware across all steps

**What is not touched:**
- `prototype/core/` — state machine, event log, orchestrator, actors
- `prototype/llm/` — structurer, email_agent
- Any `_vs_step_*` function in `user_app.py`
- Any `_inst_*` function in `user_app.py`
- Option B of Stellenwechsel (the existing flow)
- The onboarding flow (`_show_onboarding`)
- The login page (`_page_login`)

---

## 2. Architecture — Slim Router (Approach B)

New capabilities live in dedicated modules imported into `user_app.py`. The existing file is extended only at its router (`main()`) and imports section.

### 2.1 New files

```
prototype/ui/
  hv_styles.py              # shared CSS constants imported by all new modules
  hv_utils.py               # shared utilities: _extract_doc_info, LLM client init
  hv_profile.py             # profile collection UI + MongoDB persistence
  hv_dashboard.py           # scenario selection page (replaces _scenario_selection_page)
  hv_option_cards.py        # per-scenario A/B/C/D picker + status badges
  hv_chat.py                # floating chat panel — inject + render
  hv_options/
    __init__.py
    stellenwechsel_a.py     # Dokumente verstehen
    stellenwechsel_c.py     # Diagnostic chat (Stellenwechsel)
    stellenwechsel_d.py     # LPP-Einkauf verstehen
    revue_avs_a.py          # IK-Auszug verstehen
    revue_avs_b.py          # thin redirect to existing revue_avs flow
    revue_avs_c.py          # Diagnostic chat (AVS)
    revue_avs_d.py          # AVS-Lücke schliessen
```

**Note on `hv_utils.py`:** `_extract_doc_info()` currently lives in `user_app.py` as a private function. Since option modules cannot import from `user_app.py` without creating a circular import, this function is extracted into `hv_utils.py` during implementation. `user_app.py` is updated to import it from there. This is the only function moved — nothing else in `user_app.py` is touched.

Each option module exports exactly one public function: `render(profile: dict, case: dict) -> None`.

### 2.2 Changes to user_app.py

Exactly four categories of change, nowhere else:

1. **Imports** — new import lines at top of file (one per new module)
2. **`_inject_css()`** — unchanged; new shared CSS lives in `hv_styles.py`
3. **`main()`** — routing branches added; see Section 3
4. **`_scenario_selection_page()`** — call replaced by `hv_dashboard.render()`; the function body is retained in the file until the full routing is verified, then removed

---

## 3. Routing Flow

```
main()
  │
  ├── hv_chat.inject()                          # always first — injects fixed CSS/panel
  ├── _inject_css()                             # existing (unchanged)
  │
  ├── onboarding_done?  → NO  → _show_onboarding()        [existing, unchanged]
  │                    ↓ YES
  ├── logged_in?        → NO  → _page_login()              [existing, unchanged]
  │                    ↓ YES
  ├── profile_complete? → NO  → hv_profile.render()        [NEW]
  │                    ↓ YES
  ├── scenario_selected? → NO → hv_dashboard.render()      [NEW, replaces old]
  │                     ↓ YES
  ├── option_selected?  → NO  → hv_option_cards.render()   [NEW]
  │                    ↓ YES
  └── dispatch:
        stellenwechsel + B  →  existing _vs_step_* flow    [UNTOUCHED]
        stellenwechsel + A  →  stellenwechsel_a.render()
        stellenwechsel + C  →  stellenwechsel_c.render()
        stellenwechsel + D  →  stellenwechsel_d.render()
        revue_avs + A       →  revue_avs_a.render()
        revue_avs + B       →  revue_avs_b.render()
        revue_avs + C       →  revue_avs_c.render()
        revue_avs + D       →  revue_avs_d.render()
        institution role    →  existing _inst_* flow        [UNTOUCHED]
```

### 3.1 New session state keys

```python
"selected_option"           # "A" | "B" | "C" | "D"
"profile_complete"          # bool — True once profile saved to MongoDB
"profile_data"              # dict — mirrors MongoDB profile document
"chat_open"                 # bool — floating panel open/closed
"chat_messages_global"      # list[dict] — persistent chat history (not per-step)
"option_statuses"           # dict — {scenario: {option: status_str}}
```

All existing session state keys are unchanged.

---

## 4. Universal User Profile

### 4.1 Fields

| Field | Type | Source |
|---|---|---|
| `vorname` | str | Pre-filled from login |
| `nachname` | str | Pre-filled from login |
| `zivilstand` | str | ledig / verheiratet / geschieden / verwitwet |
| `geburtsjahr` | int | Select |
| `kinder` | bool | Checkbox |
| `anstellung` | str | angestellt / selbständig / arbeitslos / anderes |
| `uploaded_doc_ids` | list[str] | MongoDB GridFS IDs (optional) |

### 4.2 Timing

Rendered by `hv_profile.render()` immediately after first login, before scenario selection. The function reads from MongoDB first — if a profile document exists for `user_email`, it loads silently into `st.session_state.profile_data` and sets `profile_complete = True` without showing the form.

### 4.3 Pre-fill from documents

Any document uploaded at any option screen (via `_extract_doc_info()`) patches the profile dict in session state and MongoDB. Fields already present are never overwritten without explicit user action.

### 4.4 MongoDB schema

```json
{
  "user_email": "user@example.com",
  "vorname": "Max",
  "nachname": "Muster",
  "zivilstand": "ledig",
  "geburtsjahr": 1985,
  "kinder": false,
  "anstellung": "angestellt",
  "uploaded_doc_ids": [],
  "profile_version": 1,
  "created_at": "2026-04-20T...",
  "updated_at": "2026-04-20T..."
}
```

Collection: `user_profiles` (new, separate from `cases`).

---

## 5. Scenario Dashboard (`hv_dashboard.py`)

Replaces `_scenario_selection_page()`. Sets `st.session_state.selected_scenario` on click and reruns — identical contract to current function.

### Layout

2×2 card grid. Cards: icon + scenario title + 2-line description + actor tags + "Jetzt starten" CTA button.

```
┌──────────────────────────────────────────────────────────┐
│  HelveVista  /  Koordination Ihrer Vorsorge              │
├────────────────────────┬─────────────────────────────────┤
│  ⚡ STELLENWECHSEL     │  📋 REVUE AVS                   │
│  Koordination BVG      │  IK-Auszug und Beitragslücken   │
│  • Alte PK             │  • AHV-Ausgleichskasse          │
│  • Neue PK             │  • Optionale PK                 │
│  [ Jetzt starten ]     │  [ Jetzt starten ]              │
├────────────────────────┼─────────────────────────────────┤
│  ♥ ZIVILSTANDSÄNDERUNG │  ⏰ PENSIONIERUNG               │
│  (opacity 0.45)        │  (opacity 0.45)                 │
│  In Entwicklung        │  In Entwicklung                 │
└────────────────────────┴─────────────────────────────────┘
```

Design: dark navy `#0F1E2E`, gold `#C9A84C`, cards at `#122033`, border `#1A3048`. Identical to existing design language.

---

## 6. Option Cards (`hv_option_cards.py`)

Rendered after scenario selection and after profile completion. Shows 4 options in a 2×2 grid. Sets `st.session_state.selected_option` on click and reruns.

### Card structure

Each card: gold letter badge (A/B/C/D) + title + 2-line description + status badge + "Wählen" button.

### Stellenwechsel options

| Option | Title | Description | Notes |
|---|---|---|---|
| A | Dokumente verstehen | Laden Sie Ihren Vorsorgeausweis hoch. HelveVista erklärt jeden Abschnitt. | Educational, no institution contact |
| B | Démarches starten | Der vollständige 6-Schritt-Koordinationsprozess mit Ihren Pensionskassen. | Existing flow — UNTOUCHED |
| C | Ich weiss nicht wo anfangen | Beschreiben Sie Ihre Situation. HelveVista analysiert und empfiehlt den richtigen Weg. | Free-form diagnostic chat |
| D | LPP-Einkauf verstehen | Verstehen Sie die Vorteile eines freiwilligen Einkaufs und beantragen Sie ein Zertifikat. | Educational + PK contact |

### Revue AVS options

| Option | Title | Description | Notes |
|---|---|---|---|
| A | IK-Auszug verstehen | Laden Sie Ihren IK-Auszug hoch. HelveVista erklärt Beitragsjahre und Lücken. | Educational, 12-month freshness check |
| B | Anfrage stellen | Strukturierte Anfrage an die AHV-Ausgleichskasse. | Thin wrapper → existing AVS flow |
| C | Ich weiss nicht wo anfangen | Beschreiben Sie Ihre Situation. HelveVista analysiert und empfiehlt den richtigen Weg. | Free-form diagnostic chat, AVS-focused |
| D | AVS-Lücke schliessen | Verstehen Sie die Regeln für den freiwilligen Nachkauf und beantragen Sie konkrete Zahlen. | Educational + AHV contact |

### Status badge display

| Status key | Badge | Color |
|---|---|---|
| `not_started` | — | `#3E5F7A` (muted) |
| `in_bearbeitung` | ◉ In Bearbeitung | `#C9A84C` (gold) |
| `in_klaerung` | ◎ In Klärung | `#A08030` (muted gold) |
| `geklaert` | ✅ Geklärt | `#6FCF97` (green) |
| `anfrage_gesendet` | 📤 Anfrage gesendet | `#56B0E8` (blue) |
| `antwort_erhalten` | 📨 Antwort erhalten | `#6FCF97` (green) |
| `warten` | ⏳ Warten auf Antwort | `#7A96B0` (muted) |

Status is stored in `st.session_state.option_statuses[scenario][option]` and persisted in the case document in MongoDB (`cases` collection, existing).

---

## 7. Option Implementations

All modules: `render(profile: dict, case: dict) -> None`. No module calls `core/` directly. LLM calls use the same `anthropic.Anthropic` client pattern already in the codebase (via `hv_utils.py`).

**Case dict for option modules:** The `case` parameter is the current case document loaded from MongoDB via `_load_case()` in `user_app.py` before dispatch. Options D (both scenarios) that call `send_institution_email()` require a minimal case dict with `user_email`, `user_name`, `scenario`, and `actors_involved`. `user_app.py` constructs this minimal dict at dispatch time if no full case exists.

### 7.1 Stellenwechsel A — Dokumente verstehen

1. Document upload (`st.file_uploader`) — PDF, PNG, JPG
2. On upload: `_extract_doc_info()` (existing, reused as-is)
3. LLM call: explain each detected field in plain German
   - Fields: Freizügigkeit, Koordinationsabzug, Deckungsgrad, Umwandlungssatz
   - Tone: clear, educational, no jargon, no calculations
4. Render explanation as expandable sections per field
5. Status: `in_bearbeitung` on upload → `geklaert` when all fields explained
6. No institution contact. No state machine interaction.

### 7.2 Stellenwechsel C — Diagnostic chat

1. `st.chat_input()` for free-form situation description
2. System prompt instructs HelveVista to: ask gently, identify the core need, then recommend Option A, B, or D with a 2-sentence rationale
3. On recommendation: renders a direct-action button (e.g. "Option B starten →") that sets `selected_option` and reruns
4. Status: `in_bearbeitung` throughout → no terminal state (diagnostic only)

### 7.3 Stellenwechsel D — LPP-Einkauf verstehen

1. Educational content rendered in 4 expandable sections:
   - Steuerliche Vorteile (tax)
   - Kapitalauswirkung (capital)
   - Hypothekarische Implikationen (mortgage)
   - Timing und Pensionierung (retirement)
2. Never calculates amounts — explicit disclaimer shown
3. CTA: "Persönliches Einkaufszertifikat anfragen" → calls `send_institution_email()` to `Actor.NEW_PK`
4. Status: `in_bearbeitung` → `anfrage_gesendet` → `antwort_erhalten`

### 7.4 Revue AVS A — IK-Auszug verstehen

1. Document upload
2. `_extract_doc_info()` — extracts `beitragsjahre`, `luecken`, `issued_date`
3. **Freshness check:** if `issued_date` is more than 12 months ago → show warning banner: "Dieser IK-Auszug wurde vor mehr als 12 Monaten ausgestellt und ist möglicherweise nicht mehr aktuell."
4. LLM explains contribution years, gap implications, voluntary contribution options — no amounts
5. Status: `in_bearbeitung` → `geklaert`

### 7.5 Revue AVS B — Anfrage stellen

Thin redirect module. Sets `st.session_state.selected_scenario = "revue_avs"` with AVS-only actor configuration, then delegates to the existing step flow. No new logic — this option is already substantially implemented in `user_app.py`.

### 7.6 Revue AVS C — Diagnostic chat

Same pattern as Stellenwechsel C. System prompt is AVS-focused: gap years, IK-Auszug status, voluntary contributions, pension timing. Recommends Option A, B, or D.

### 7.7 Revue AVS D — AVS-Lücke schliessen

1. Educational content in 3 sections:
   - Wer ist betroffen (eligibility)
   - Zeitfenster (5-year voluntary contribution window)
   - Ablauf der Nachzahlung (procedure)
2. Never calculates amounts — explicit disclaimer
3. CTA: "Genaue Zahlen anfragen bei der AHV-Ausgleichskasse" → `send_institution_email()` to `Actor.AVS`
4. Status: `in_bearbeitung` → `anfrage_gesendet` → `antwort_erhalten`

---

## 8. Floating Chat (`hv_chat.py`)

### 8.1 Implementation approach

`hv_chat.inject()` is called at the top of `main()` before any page rendering. It does two things:

1. **CSS injection** via `st.markdown(unsafe_allow_html=True)`: injects a `position: fixed; bottom: 20px; right: 20px; z-index: 9999` panel with the HelveVista design language (dark navy background, gold header bar)
2. **Toggle button**: a Streamlit button styled via CSS to appear as a gold pill (💬) at bottom-right when `chat_open = False`. On click: sets `chat_open = True` and reruns.

When `chat_open = True`, a `st.chat_input()` is rendered at the bottom of `main()` (after all page content). CSS repositions it visually inside the panel. Previous messages are rendered as HTML inside the injected panel div.

A close button (✕) in the panel header sets `chat_open = False` on click.

### 8.2 Context injection

Every LLM call from the floating chat receives this system context:

```python
system = f"""
Du bist HelveVista, ein Vorsorge-Assistent für das Schweizer 3-Säulen-System.
Du eduzierts und verbindest — du rechnest nie.

Aktueller Kontext:
- Szenario: {selected_scenario}
- Option: {selected_option}
- Schritt (falls Option B): {vs_step}
- Nutzerprofil: {profile_data}
- Fallstatus: {actor_states_summary}
"""
```

This makes every answer specific to where the user is in the flow without requiring them to re-explain their situation.

### 8.3 Chat history

Stored in `st.session_state.chat_messages_global` — separate from `sparring_messages` (which is step-specific and unmodified). Persists for the session lifetime. Not persisted to MongoDB (session-scoped by design — the chat is a live assistant, not a record).

### 8.4 "Omnipresent" behavior per the spec

- At scenario selection: chat available, context = "no scenario selected yet"
- At option selection: chat available, context = scenario name
- Inside any option: chat available, full context

The chat pops up automatically (pre-opened, `chat_open = True`) on first visit to the scenario dashboard and on first visit to the option selection screen. Subsequently, state is user-controlled.

---

## 9. Constraints and Non-Goals

| Constraint | Reason |
|---|---|
| No `core/` modifications | Thesis architectural invariant (CLAUDE.md §1) |
| No LLM-driven state transitions | Thesis hypothesis H1 safety guarantee |
| HelveVista never calculates amounts | Domain rule — prevents legal liability in prototype |
| No new external dependencies | CLAUDE.md: only `anthropic` and `pytest` |
| Floating chat does not persist to MongoDB | Session-scoped assistant; case data is the permanent record |
| Option B flows unchanged | Working prototype must not regress |

---

## 10. Implementation Priority Order

Per user specification:

1. **Scenario dashboard** (`hv_dashboard.py`) — replaces landing page
2. **Option routing** (`hv_option_cards.py` + dispatch in `main()`) — connects dashboard to flows
3. **Floating chat** (`hv_chat.py`) — omnipresent assistant
4. **Universal profile** (`hv_profile.py`) — collected once, reused everywhere
5. **Option modules** — in parallel once routing is wired: A/C/D for both scenarios

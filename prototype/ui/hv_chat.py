"""
ui/hv_chat.py
-------------
Persistent floating chat assistant for HelveVista 2.0 — PALLIER 4 redesign.
inject() is called at the top of main() to render the FAB button and CSS.
render_panel() is called at the bottom of main() when chat_open=True.
"""
from __future__ import annotations
import html as _html_lib
import os
import streamlit as st
import streamlit.components.v1 as _components
import anthropic
from ui.hv_styles import HV_DARK  # noqa: F401 — kept for future callers

MODEL = "claude-sonnet-4-20250514"

_OPENING_MSG = (
    "Guten Tag! \U0001f44b Ich bin HelveVista, Ihr persönlicher Vorsorge-Assistent. "
    "Wie kann ich Ihnen helfen? Ich kann Ihnen auch helfen, die richtige Option "
    "für Ihre Situation zu finden."
)

# Options A, B, C, D embed their own chat — the floating chat is suppressed there.
_OWN_CHAT_OPTIONS = {"A", "B", "C", "D"}

# ── CSS ───────────────────────────────────────────────────────────────────────
_CSS = """
<style>
@keyframes hv-fab-popin {
    0%   { transform: scale(0) rotate(-10deg); opacity: 0; }
    70%  { transform: scale(1.15) rotate(4deg); opacity: 1; }
    100% { transform: scale(1)  rotate(0deg);  opacity: 1; }
}
@keyframes hv-slide-up {
    from { transform: translateY(20px); opacity: 0; }
    to   { transform: translateY(0);    opacity: 1; }
}

/* ── FAB ──────────────────────────────────────── */
div[data-testid="stVerticalBlock"]:has(button[aria-label="💬"]) {
    position: fixed !important;
    bottom: 22px !important;
    right:  22px !important;
    z-index: 9999 !important;
    width: auto !important;
}
button[aria-label="💬"] {
    background:   #C9A84C !important;
    color:        #0F1E2E !important;
    border-radius: 50% !important;
    width:  56px !important;
    height: 56px !important;
    min-height: 56px !important;
    padding: 0 !important;
    border: none !important;
    box-shadow: 0 4px 20px rgba(201,168,76,0.40) !important;
    font-size: 1.5rem !important;
    line-height: 1 !important;
    cursor: pointer !important;
    animation: hv-fab-popin 0.5s cubic-bezier(0.175,0.885,0.32,1.275) 0.2s both !important;
    transition: transform 0.15s ease, box-shadow 0.15s ease !important;
}
button[aria-label="💬"]:hover {
    transform:  scale(1.08) !important;
    box-shadow: 0 6px 24px rgba(201,168,76,0.55) !important;
}

/* ── Chat panel — class injected by JS positioner, avoids :has() bubbling ── */
.hv-panel-positioned {
    position: fixed !important;
    bottom: 94px !important;
    right:  22px !important;
    width:  480px !important;
    z-index: 9998 !important;
    background: #0d2137 !important;
    border: 1px solid #1A3048 !important;
    border-radius: 16px !important;
    overflow: hidden !important;
    box-shadow: 0 16px 48px rgba(0,0,0,0.65) !important;
    box-sizing: border-box !important;
    animation: hv-slide-up 0.3s ease-out both !important;
}

/* strip default Streamlit padding from direct children */
.hv-panel-positioned > div {
    padding: 0 !important;
    margin:  0 !important;
    max-width: 100% !important;
}

/* header columns block */
.hv-panel-positioned > div[data-testid="stHorizontalBlock"] {
    flex-shrink: 0 !important;
    background: linear-gradient(135deg,#071220 0%,#0d2137 55%,#0f2845 100%) !important;
    border-bottom: 1px solid rgba(201,168,76,0.22) !important;
    align-items: center !important;
}
.hv-panel-positioned > div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
    padding: 0 !important;
}

/* message iframe — seamless, no default iframe border */
.hv-panel-positioned iframe {
    display: block !important;
    border: none !important;
    width: 100% !important;
    background: #0d2137 !important;
}

/* textarea */
.hv-panel-positioned textarea {
    background:    #091520 !important;
    border: none !important;
    border-top: 1px solid #1A3048 !important;
    color: #C8D8E8 !important;
    resize: none !important;
    font-size: 0.875rem !important;
    border-radius: 0 !important;
    padding: 10px 14px !important;
    min-height: 60px !important;
    box-shadow: none !important;
}
.hv-panel-positioned textarea:focus {
    box-shadow: none !important;
    border-color: rgba(201,168,76,0.45) !important;
}

/* send button */
.hv-panel-positioned [data-testid="stBaseButton-secondary"] > button,
.hv-panel-positioned [data-testid="stButton"] > button {
    background: #C9A84C !important;
    color: #0d2137 !important;
    border: none !important;
    font-weight: 700 !important;
    border-radius: 0 0 14px 14px !important;
    width: 100% !important;
    padding: 10px !important;
    font-size: 0.9rem !important;
    letter-spacing: 0.3px !important;
    transition: background 0.15s ease !important;
}
.hv-panel-positioned [data-testid="stBaseButton-secondary"] > button:hover,
.hv-panel-positioned [data-testid="stButton"] > button:hover {
    background: #d4b460 !important;
}

/* close button */
.hv-panel-positioned button[aria-label="✕"] {
    background: transparent !important;
    color: #7A96B0 !important;
    border: none !important;
    font-size: 1rem !important;
    padding: 4px 6px !important;
    min-height: unset !important;
    line-height: 1 !important;
    box-shadow: none !important;
    transition: color 0.15s !important;
}
.hv-panel-positioned button[aria-label="✕"]:hover {
    color: #C9A84C !important;
}

/* hide textarea label */
.hv-panel-positioned label {
    display: none !important;
}
</style>
"""

# ── Web Audio pop sound injected via same-origin iframe ───────────────────────
_AUDIO_JS = """
<script>
(function() {
    function beep() {
        try {
            var AC = window.AudioContext || window.webkitAudioContext;
            if (!AC) return;
            var ctx = new AC();
            var osc  = ctx.createOscillator();
            var gain = ctx.createGain();
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.type = 'sine';
            osc.frequency.setValueAtTime(660, ctx.currentTime);
            osc.frequency.linearRampToValueAtTime(880, ctx.currentTime + 0.10);
            gain.gain.setValueAtTime(0.07, ctx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.28);
            osc.start(ctx.currentTime);
            osc.stop(ctx.currentTime + 0.28);
        } catch(e) {}
    }
    function attach() {
        try {
            var btn = window.parent.document.querySelector('button[aria-label="💬"]');
            if (btn && !btn._hvBeep) { btn.addEventListener('click', beep); btn._hvBeep = true; }
        } catch(e) {}
    }
    attach();
    setTimeout(attach,  600);
    setTimeout(attach, 1800);
})();
</script>
"""

# ── JS panel positioner ───────────────────────────────────────────────────────
# Injected via components.html(height=0). Finds the sentinel element in the
# parent document, walks up to the NEAREST stVerticalBlock (not all ancestors),
# and adds the class that CSS uses for positioning. This replaces the broken
# :has(.hv-chat-panel-marker) approach which matched every ancestor container.
_PANEL_POSITIONER_TMPL = """
<script>
(function(v) {{
    function go() {{
        try {{
            var d = window.parent.document;
            var s = d.getElementById('hv-chat-sentinel');
            if (!s) return false;
            var b = s.closest('[data-testid="stVerticalBlock"]');
            if (!b) return false;
            b.classList.add('hv-panel-positioned');
            return true;
        }} catch(e) {{ return false; }}
    }}
    if (!go()) {{
        setTimeout(go, 150);
        setTimeout(go, 500);
        setTimeout(go, 1200);
    }}
}})({version});
</script>
"""


# ── Context + system prompt ───────────────────────────────────────────────────

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
    if ctx["option"] == "—":
        return (
            "Du bist HelveVista — auf dieser Seite AUSSCHLIESSLICH als Wegweiser für die Optionenwahl.\n\n"
            "DEINE EINZIGE AUFGABE: Erkläre, was jede Option bedeutet, und empfehle, "
            "welche am besten zur Situation des Nutzers passt.\n\n"
            "Du DARFST NIEMALS: Daten sammeln, Koordinationsverfahren einleiten, "
            "Analysen starten, Aufgaben ausführen oder irgendeinen Prozess starten.\n\n"
            "Die 4 Optionen:\n"
            "A) Dokumente verstehen — Vorsorgeausweis oder IK-Auszug hochladen und erklären lassen.\n"
            "B) Koordinationsverfahren einleiten — 6-Schritt-Prozess für Stellenwechsel oder AHV-Anfrage.\n"
            "C) Ich weiss nicht wo anfangen — HelveVista analysiert die Situation.\n"
            "D) LPP-Einkauf / AVS-Lücke verstehen.\n\n"
            "Falls der Nutzer fragt, etwas zu starten oder durchzuführen: "
            "Antworte mit: 'Bitte wählen Sie Option B, dann begleite ich Sie Schritt für Schritt.'\n\n"
            "STIL: Deutsch, freundlich, maximal 3 Sätze pro Antwort. "
            "Beende JEDE Antwort mit einer klaren Empfehlung, welche Option am besten passt."
        )
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


# ── Message bubble HTML ───────────────────────────────────────────────────────

def _build_messages_html(messages: list[dict]) -> str:
    parts = []
    for msg in messages[-20:]:
        role = msg["role"]
        text = _html_lib.escape(msg["content"]).replace("\n", "<br>")
        if role == "assistant":
            parts.append(
                '<div style="display:flex;gap:8px;align-items:flex-start;margin-bottom:10px;">'
                '<div style="background:#C9A84C;color:#0d2137;width:28px;height:28px;'
                'border-radius:50%;display:flex;align-items:center;justify-content:center;'
                'font-size:10px;font-weight:800;flex-shrink:0;letter-spacing:-0.5px;">HV</div>'
                '<div style="background:#0d2137;border-left:3px solid #C9A84C;'
                'border-radius:0 12px 12px 12px;padding:10px 14px;max-width:80%;'
                f'font-size:0.875rem;line-height:1.55;color:#C8D8E8;word-wrap:break-word;">{text}</div>'
                '</div>'
            )
        else:
            parts.append(
                '<div style="display:flex;gap:8px;align-items:flex-start;'
                'justify-content:flex-end;margin-bottom:10px;">'
                '<div style="background:#1a3a5c;border-right:3px solid #C9A84C;'
                'border-radius:12px 0 12px 12px;padding:10px 14px;max-width:80%;'
                f'font-size:0.875rem;line-height:1.55;color:#C8D8E8;word-wrap:break-word;">{text}</div>'
                '</div>'
            )
    return "\n".join(parts)


def _build_messages_iframe_html(messages: list[dict]) -> str:
    """Self-contained HTML page for the scrollable message history iframe."""
    bubbles = _build_messages_html(messages)
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<style>'
        '*{box-sizing:border-box;margin:0;padding:0}'
        'html,body{height:100%;background:#0d2137;'
        'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;'
        'overflow-y:auto;scrollbar-width:thin;scrollbar-color:#1A3048 transparent}'
        'body::-webkit-scrollbar{width:4px}'
        'body::-webkit-scrollbar-thumb{background:#1A3048;border-radius:2px}'
        '.msgs{padding:14px 12px;display:flex;flex-direction:column}'
        '</style></head>'
        f'<body><div class="msgs">{bubbles}</div>'
        '<script>window.scrollTo(0,document.body.scrollHeight);</script>'
        '</body></html>'
    )


# ── Public API ────────────────────────────────────────────────────────────────

def inject() -> None:
    """
    Inject the floating chat FAB button and CSS.
    Must be called at the very top of main(), before any page content.
    Suppresses floating chat on option pages that have their own embedded chat (A/B/C/D).
    The option picker page (selected_option=None) keeps the chat active.
    On the picker page, render_panel() is called inline here because main() returns early
    before reaching its own render_panel() call.
    """
    current_option = st.session_state.get("selected_option")

    # Clear history whenever selected_option changes.
    if "_prev_chat_option" not in st.session_state:
        st.session_state["_prev_chat_option"] = current_option
    elif st.session_state["_prev_chat_option"] != current_option:
        st.session_state["chat_messages_global"] = []
        st.session_state["_prev_chat_option"] = current_option

    # Suppress on own-chat options; the picker page (None) is allowed.
    if current_option in _OWN_CHAT_OPTIONS:
        st.session_state["chat_open"] = False
        return

    # Initialise session state
    if "chat_messages_global" not in st.session_state:
        st.session_state.chat_messages_global = []
    if "chat_open" not in st.session_state:
        st.session_state.chat_open = False
    if "chat_input_cycle" not in st.session_state:
        st.session_state.chat_input_cycle = 0

    # Auto-open: immediately on picker page; on other pages only after login+scenario.
    if current_option is None:
        if not st.session_state.get("_chat_auto_opened_picker"):
            st.session_state.chat_open = True
            st.session_state["_chat_auto_opened_picker"] = True
    else:
        scenario = st.session_state.get("selected_scenario")
        if scenario and st.session_state.get("logged_in"):
            page_key = f"_chat_auto_opened_{scenario}_{current_option}"
            if not st.session_state.get(page_key):
                st.session_state.chat_open = True
                st.session_state[page_key] = True

    # Inject CSS
    st.markdown(_CSS, unsafe_allow_html=True)

    # Inject audio script via same-origin iframe
    _components.html(_AUDIO_JS, height=0)

    # FAB always visible; click toggles chat open/closed.
    if st.button("\U0001f4ac", key="chat-fab-btn"):
        st.session_state.chat_open = not st.session_state.chat_open
        st.rerun()

    # On the picker page main() returns early — render panel inline.
    if current_option is None and st.session_state.get("chat_open"):
        render_panel()


def render_panel() -> None:
    """
    Render the floating chat window.

    Architecture: uses components.html() for the scrollable message history so it
    lives inside a self-contained iframe — no Streamlit CSS :has() tricks needed
    for the message area. The container itself is positioned via a JS snippet
    (also in a zero-height iframe) that finds the sentinel element, walks up to
    the nearest stVerticalBlock, and adds the class .hv-panel-positioned, which
    CSS uses for fixed positioning. This avoids :has() bubbling to ancestor blocks.
    """
    if not st.session_state.chat_messages_global:
        st.session_state.chat_messages_global.append(
            {"role": "assistant", "content": _OPENING_MSG}
        )

    input_cycle = st.session_state.get("chat_input_cycle", 0)
    # Include message count in positioner so the iframe content changes when a
    # new message arrives, forcing Streamlit to re-deliver the script to the frame.
    n_msgs = len(st.session_state.chat_messages_global)
    positioner_js = _PANEL_POSITIONER_TMPL.format(version=n_msgs * 1000 + input_cycle)

    with st.container():
        # Sentinel: the JS positioner uses getElementById to locate this element,
        # then climbs to the nearest stVerticalBlock to add .hv-panel-positioned.
        st.markdown(
            '<span id="hv-chat-sentinel" style="display:none;height:0;overflow:hidden"></span>',
            unsafe_allow_html=True,
        )

        # Zero-height iframe: runs positioner JS in the same origin as the app.
        _components.html(positioner_js, height=0)

        # Header row: gradient title on the left, close button on the right.
        col_hdr, col_x = st.columns([10, 1])
        with col_hdr:
            st.markdown(
                '<div class="hv-chat-header-inner" style="'
                'display:flex;align-items:center;gap:10px;padding:14px 16px 12px;">'
                '<div style="background:#C9A84C;color:#0d2137;width:30px;height:30px;'
                'border-radius:50%;display:flex;align-items:center;justify-content:center;'
                'font-size:10px;font-weight:800;letter-spacing:-0.5px;flex-shrink:0;">HV</div>'
                '<div>'
                '<div style="color:#C9A84C;font-size:0.95rem;font-weight:700;'
                'line-height:1.2;letter-spacing:0.2px;">HelveVista</div>'
                '<div style="color:#7A96B0;font-size:0.72rem;line-height:1.3;">'
                'Ihr Vorsorge-Assistent</div>'
                '</div></div>',
                unsafe_allow_html=True,
            )
        with col_x:
            if st.button("✕", key="chat-close-btn"):
                st.session_state.chat_open = False
                st.rerun()

        # Self-contained iframe for the scrollable message history.
        # No Streamlit CSS inheritance, no :has() selector issues.
        _components.html(
            _build_messages_iframe_html(st.session_state.chat_messages_global),
            height=300,
        )

        # Input zone kept as native Streamlit widgets so they participate in
        # the normal Streamlit rerun / session-state cycle.
        user_input = st.text_area(
            "Nachricht",
            key=f"chat_input_{input_cycle}",
            height=80,
            label_visibility="collapsed",
            placeholder="Ihre Frage…",
        )
        send = st.button(
            "Senden →",
            key=f"chat_send_{input_cycle}",
            use_container_width=True,
        )

    if send and user_input and user_input.strip():
        st.session_state.chat_messages_global.append(
            {"role": "user", "content": user_input.strip()}
        )
        st.session_state.chat_input_cycle = input_cycle + 1

        ctx = build_chat_context(
            scenario=st.session_state.get("selected_scenario"),
            option=st.session_state.get("selected_option"),
            vs_step=st.session_state.get("vs_step", 1),
            profile=st.session_state.get("profile_data", {}),
            actor_states=st.session_state.get("case", {}).get("actor_states", {}),
        )
        with st.spinner("HelveVista schreibt…"):
            answer = _llm_answer(user_input.strip(), ctx)

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

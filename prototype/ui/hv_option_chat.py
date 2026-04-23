"""
ui/hv_option_chat.py
---------------------
Shared integrated chat component for HelveVista option pages (A and D).
Renders a dark-styled chat section below page content with key-cycled
text_area input and LLM responses via the Anthropic API.
"""
from __future__ import annotations
import os
import streamlit as st
import anthropic

MODEL = "claude-sonnet-4-6"


def _llm_call(question: str, system: str, display_history: list[dict]) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return "LLM nicht verfügbar (ANTHROPIC_API_KEY fehlt)."
    try:
        client = anthropic.Anthropic(api_key=api_key)
        # Build API-safe list: must start with user, strictly alternating.
        # The opening assistant message is display-only and excluded from API calls.
        api_msgs = [
            {"role": m["role"], "content": m["content"]}
            for m in display_history
            if m["role"] in ("user", "assistant")
        ]
        while api_msgs and api_msgs[0]["role"] == "assistant":
            api_msgs.pop(0)
        api_msgs.append({"role": "user", "content": question})
        api_msgs = api_msgs[-10:]
        resp = client.messages.create(
            model=MODEL,
            max_tokens=512,
            system=system,
            messages=api_msgs,
        )
        return resp.content[0].text.strip()
    except Exception as exc:
        return f"Fehler beim LLM-Aufruf: {exc}"


def render_option_chat(
    session_key: str,
    system_prompt: str,
    opening_msg: str,
    title: str = "Fragen? HelveVista antwortet",
    emoji: str = "🛡️",
) -> None:
    """
    Render an integrated chat section at the bottom of an option page.

    Parameters:
        session_key:   Unique state key prefix (e.g. "chat_a_sw").
        system_prompt: LLM system prompt for this page's topic.
        opening_msg:   Auto-displayed first assistant message.
        title:         Header label shown in the gold chat bar.
        emoji:         Icon shown in the chat header (default 🛡️).
    """
    msgs_key  = f"{session_key}_messages"
    cycle_key = f"{session_key}_cycle"

    if msgs_key not in st.session_state:
        st.session_state[msgs_key] = []
    if cycle_key not in st.session_state:
        st.session_state[cycle_key] = 0

    messages: list[dict] = st.session_state[msgs_key]
    if not messages:
        messages.append({"role": "assistant", "content": opening_msg})

    # ── Section divider + title ──────────────────────────────────────────────
    st.markdown(
        """
<div style="display:flex; align-items:center; gap:12px; margin:2rem 0 1.2rem;">
  <div style="flex:1; height:1px; background:linear-gradient(to right,#1e3d5c,transparent);"></div>
  <span style="color:#C9A84C; font-size:0.78rem; font-weight:600;
               letter-spacing:0.18em; white-space:nowrap;">GESPRÄCH MIT HELVEVISTA</span>
  <div style="flex:1; height:1px; background:linear-gradient(to left,#1e3d5c,transparent);"></div>
</div>
""",
        unsafe_allow_html=True,
    )

    # ── Outer container ──────────────────────────────────────────────────────
    st.markdown(
        f"""
<div style="background:#07131d; border:1.5px solid #2a4a66;
            border-radius:16px; overflow:hidden; box-shadow:0 8px 32px rgba(0,0,0,0.45);">
  <!-- Gradient header -->
  <div style="background:linear-gradient(135deg,#0d2137 0%,#112b44 60%,#0d2137 100%);
              padding:14px 22px; border-bottom:1px solid #C9A84C;
              display:flex; align-items:center; gap:10px;">
    <span style="font-size:1.1rem;">{emoji}</span>
    <span style="color:#C9A84C; font-weight:700; font-size:0.95rem;
                 letter-spacing:0.06em;">HelveVista</span>
    <span style="color:#4a7a9b; font-size:0.78rem; margin-left:4px;">— Ihr Vorsorge-Assistent</span>
  </div>
""",
        unsafe_allow_html=True,
    )

    # ── Message thread ────────────────────────────────────────────────────────
    st.markdown(
        '<div style="padding:20px 20px 8px; display:flex; flex-direction:column; gap:16px;">',
        unsafe_allow_html=True,
    )

    for msg in messages:
        if msg["role"] == "assistant":
            st.markdown(
                f"""
<div style="display:flex; align-items:flex-start; gap:10px; max-width:92%;">
  <div style="flex-shrink:0; width:28px; height:28px; border-radius:50%;
              background:#C9A84C; display:flex; align-items:center; justify-content:center;
              font-size:0.62rem; font-weight:800; color:#07131d; letter-spacing:0.03em;
              margin-top:2px;">HV</div>
  <div style="background:#0d2137; border-left:3px solid #C9A84C;
              border-radius:4px 14px 14px 14px;
              padding:14px 18px; flex:1;
              color:#d8e8f4; font-size:1rem; line-height:1.75;">
    {msg["content"]}
  </div>
</div>
""",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"""
<div style="display:flex; align-items:flex-start; justify-content:flex-end; gap:10px;">
  <div style="background:#1a3a5c; border-right:3px solid #C9A84C;
              border-radius:14px 4px 14px 14px;
              padding:12px 16px; max-width:82%;
              color:#e8f2fa; font-size:1rem; line-height:1.7;">
    {msg["content"]}
  </div>
  <div style="flex-shrink:0; width:28px; height:28px; border-radius:50%;
              background:#1a3a5c; border:1.5px solid #C9A84C;
              display:flex; align-items:center; justify-content:center;
              font-size:0.85rem; margin-top:2px;">👤</div>
</div>
""",
                unsafe_allow_html=True,
            )

    st.markdown("</div>", unsafe_allow_html=True)

    # ── Input zone ────────────────────────────────────────────────────────────
    st.markdown(
        '<div style="padding:0 20px 20px;">',
        unsafe_allow_html=True,
    )

    cycle = st.session_state[cycle_key]
    user_text = st.text_area(
        "Frage",
        key=f"{session_key}_input_{cycle}",
        height=90,
        label_visibility="collapsed",
        placeholder="Stellen Sie Ihre Frage…",
    )

    _, col_btn = st.columns([4, 1])
    with col_btn:
        send = st.button(
            "Senden →",
            key=f"{session_key}_send_{cycle}",
            use_container_width=True,
            type="primary",
        )

    st.markdown("</div></div>", unsafe_allow_html=True)

    if send and user_text.strip():
        messages.append({"role": "user", "content": user_text.strip()})
        st.session_state[cycle_key] = cycle + 1
        with st.spinner("HelveVista arbeitet…"):
            answer = _llm_call(user_text.strip(), system_prompt, messages[:-1])
        messages.append({"role": "assistant", "content": answer})
        st.rerun()

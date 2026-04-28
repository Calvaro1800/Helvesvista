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
    import streamlit as st
    try:
        debug_key = st.secrets.get("ANTHROPIC_API_KEY")
        st.write(f"DEBUG: secret key found = {bool(debug_key)}, env key found = {bool(os.environ.get('ANTHROPIC_API_KEY'))}")
    except Exception as e:
        st.write(f"DEBUG: secrets error = {e}")
    try:
        import streamlit as st
        api_key = st.secrets.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    except Exception:
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
        "Analysiere dieses Vorsorge-Dokument (Vorsorgeausweis ODER IK-Auszug) und extrahiere alle verfügbaren Informationen. "
        "Für einen Vorsorgeausweis hat das Dokument zwei Abschnitte: 'Alter Arbeitgeber' und 'Neuer Arbeitgeber'. "
        "Extrahiere diese Felder getrennt:\n"
        "- arbeitgeber / arbeitgeber_ort / email: aus dem Abschnitt 'Alter Arbeitgeber'\n"
        "- neuer_arbeitgeber / ort_neuer_ag / email_neue_pk: aus dem Abschnitt 'Neuer Arbeitgeber'\n"
        "- eintrittsdatum: Eintrittsdatum beim alten Arbeitgeber (Alter Arbeitgeber)\n"
        "- eintrittsdatum_neu: Eintrittsdatum beim neuen Arbeitgeber (Neuer Arbeitgeber), falls vorhanden\n"
        "Für einen IK-Auszug (Individueller Kontenauszug der AHV) extrahiere zusätzlich aus dem Abschnitt 'Zusammenfassung':\n"
        "- beitragsjahre: Anzahl Beitragsjahre, z.B. '18 Jahre (2007–2024)'\n"
        "- beitragsluecken: Beitragslücken, z.B. 'Keine' oder eine Beschreibung\n"
        "- ausgleichskasse: Name der Ausgleichskasse, z.B. 'SVA Zürich'\n"
        "- email_avs: E-Mail der Ausgleichskasse (Feld 'E-Mail Ausgleichskasse')\n"
        "Antworte NUR mit JSON:\n"
        '{"name":null,"geburtsdatum":null,"ahv_nummer":null,"pensionskasse":null,'
        '"arbeitgeber":null,"arbeitgeber_ort":null,"freizuegigkeit_chf":null,'
        '"koordinationsabzug_chf":null,"austrittsdatum":null,"eintrittsdatum":null,'
        '"email":null,"telefon":null,"issued_date":null,'
        '"neuer_arbeitgeber":null,"ort_neuer_ag":null,"email_neue_pk":null,"eintrittsdatum_neu":null,'
        '"beitragsjahre":null,"beitragsluecken":null,"ausgleichskasse":null,"email_avs":null}\n'
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

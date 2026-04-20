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

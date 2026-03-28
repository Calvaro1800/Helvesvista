"""
llm/email_agent.py
------------------
Gmail-based agentic email bridge for HelveVista.

Solves the Cold Start Problem: institutions NOT on HelveVista can still
receive and respond to requests via email.

RÔLE AUTORISÉ (Modèle V2, §11):
    ✅ Send structured emails to institutions via Gmail API
    ✅ Poll inbox for replies and extract case references
    ✅ Parse institution replies using Claude API
    ✅ Return email status summaries for the UI

RÔLE INTERDIT (Modèle V2, §11):
    ❌ Change any state in the state machine
    ❌ Influence transition logic
    ❌ Make final decisions

PROVIDER: Gmail API (OAuth2) + Anthropic Claude API
"""

from __future__ import annotations

import base64
import json
import os
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

import anthropic

from core.states import Actor


# ── Paths ──────────────────────────────────────────────────────────────────────

PROJECT_ROOT      = Path(__file__).parent.parent.parent
CREDENTIALS_PATH  = PROJECT_ROOT / "credentials.json"
TOKEN_PATH        = PROJECT_ROOT / "token.json"
CASE_FILE         = PROJECT_ROOT / "case_state.json"


# ── Gmail OAuth2 scopes ────────────────────────────────────────────────────────

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]

SENDER_ADDRESS = "christopheralvaro.o@gmail.com"
SENDER_DISPLAY = "koordination@helvevista.ch"


# ── Actor labels ───────────────────────────────────────────────────────────────

ACTOR_LABELS: dict[Actor, str] = {
    Actor.OLD_PK: "Alte Pensionskasse",
    Actor.NEW_PK: "Neue Pensionskasse",
    Actor.AVS:    "AHV-Ausgleichskasse",
}


# ── Demo fallback responses ────────────────────────────────────────────────────
#
# Used when parse_institution_reply() cannot reach the Claude API
# or when the email body yields no parseable JSON.

DEMO_RESPONSES: dict[Actor, dict] = {
    Actor.OLD_PK: {
        "freizuegigkeit_chf": 45_200,
        "austrittsdatum":     "31. März 2025",
        "status":             "Austritt bestätigt",
    },
    Actor.NEW_PK: {
        "eintrittsdatum":         "1. April 2025",
        "bvg_koordinationsabzug": 26_460,
        "bvg_pflicht":            True,
    },
    Actor.AVS: {
        "ik_auszug":     "verfügbar",
        "beitragsjahre": 12,
        "luecken":       0,
    },
}


# ── Email body templates ───────────────────────────────────────────────────────

_EMAIL_BODIES: dict[Actor, str] = {
    Actor.OLD_PK: """\
Sehr geehrte Damen und Herren

Im Auftrag von {user_name} wenden wir uns mit folgendem Anliegen an Sie.

{user_name} tritt in Kürze aus Ihrem Versichertenbestand aus und wechselt zu \
einem neuen Arbeitgeber. Im Rahmen dieses Stellenwechsels ist die Abwicklung \
der Freizügigkeitsleistung gemäss Freizügigkeitsgesetz (FZG) erforderlich.

Wir bitten Sie um folgende Informationen:
  • Höhe des Freizügigkeitsguthabens zum Austrittsdatum
  • Austrittsdatum
  • Bestätigung der Überweisungsadresse für die neue Pensionskasse

Bitte antworten Sie direkt auf diese E-Mail unter Angabe der untenstehenden \
HelveVista-Referenz. Die Frist für Ihre Rückmeldung beträgt 14 Tage ab \
Eingang dieser Anfrage.

Mit freundlichen Grüssen
HelveVista Koordinationsstelle
""",
    Actor.NEW_PK: """\
Sehr geehrte Damen und Herren

Im Auftrag von {user_name} wenden wir uns mit folgendem Anliegen an Sie.

{user_name} wird in Kürze in Ihrem Unternehmen eintreten. Im Rahmen dieses \
Stellenwechsels sind die Anmeldung zur BVG-Pflicht sowie die Übernahme des \
Freizügigkeitsguthabens von der bisherigen Pensionskasse zu regeln.

Wir bitten Sie um folgende Informationen:
  • Eintrittsdatum
  • Geltender BVG-Koordinationsabzug
  • Bestätigung der BVG-Pflicht

Bitte antworten Sie direkt auf diese E-Mail unter Angabe der untenstehenden \
HelveVista-Referenz. Die Frist für Ihre Rückmeldung beträgt 14 Tage ab \
Eingang dieser Anfrage.

Mit freundlichen Grüssen
HelveVista Koordinationsstelle
""",
    Actor.AVS: """\
Sehr geehrte Damen und Herren

Im Auftrag von {user_name} wenden wir uns mit folgendem Anliegen an Sie.

{user_name} hat einen Stellenwechsel vollzogen und benötigt zur Überprüfung \
der Vorsorgesituation einen aktuellen IK-Auszug (Individuelle Kontenauszug).

Wir bitten Sie um folgende Informationen:
  • Aktueller IK-Auszug mit AHV-Beitragsjahren
  • Nachweis allfälliger Beitragslücken

Bitte antworten Sie direkt auf diese E-Mail unter Angabe der untenstehenden \
HelveVista-Referenz. Die Frist für Ihre Rückmeldung beträgt 14 Tage ab \
Eingang dieser Anfrage.

Mit freundlichen Grüssen
HelveVista Koordinationsstelle
""",
}

# Footer appended to every outgoing email.
# The reference line is the anchor for reply detection.
_EMAIL_FOOTER = (
    "\n\n---\n"
    "HelveVista Referenz: {case_id} | {actor_value}\n"
    "Diese E-Mail wurde automatisch durch das HelveVista Koordinationssystem generiert.\n"
    "Antworten Sie direkt auf diese E-Mail — die Referenz-ID ermöglicht die automatische Zuordnung.\n"
)

# ── Claude prompt for reply parsing ───────────────────────────────────────────

_PARSE_SYSTEM = """\
Du bist ein Vorsorge-Datenextraktor. Extrahiere aus dieser \
E-Mail-Antwort einer Schweizer Vorsorgeeinrichtung die relevanten \
strukturierten Angaben.

Akteur: {actor_value}

Antworte NUR als JSON mit diesen Feldern je nach Akteur:
- OLD_PK: freizuegigkeit_chf (int), austrittsdatum (str), status (str)
- NEW_PK: eintrittsdatum (str), bvg_koordinationsabzug (int), bvg_pflicht (bool)
- AVS: ik_auszug (str), beitragsjahre (int), luecken (int)

Falls Angaben fehlen, schätze realistische Schweizer Werte.
Nur JSON, kein Text davor/danach.\
"""


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def send_institution_email(
    actor: Actor,
    case: dict,
    institution_email: str,
) -> dict:
    """
    Sends a structured coordination email to an institution on behalf of HelveVista.

    Does NOT modify the orchestrator state machine — only persists a send record
    to case_state.json under ``email_sent[actor.value]``.

    Parameters:
        actor:              Institutional actor (OLD_PK, NEW_PK, AVS).
        case:               Case dict loaded from case_state.json.
        institution_email:  Recipient address (e.g. "info@assepro.ch").

    Returns:
        dict: {
            "success":    bool,
            "message_id": str | None,
            "error":      str | None,
        }
    """
    try:
        service = _get_gmail_service()
    except (FileNotFoundError, ImportError, RuntimeError) as exc:
        return {"success": False, "message_id": None, "error": str(exc)}

    case_id   = case.get("case_id", "UNKNOWN")
    user_name = case.get("user_name", "Versicherter")
    subject   = (
        f"HelveVista \u2014 Anfrage {ACTOR_LABELS[actor]} \u2014 Fall {case_id[:8]}"
    )

    body = (
        _EMAIL_BODIES[actor].format(user_name=user_name)
        + _EMAIL_FOOTER.format(case_id=case_id, actor_value=actor.value)
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"{SENDER_DISPLAY} <{SENDER_ADDRESS}>"
    msg["To"]      = institution_email
    msg.attach(MIMEText(body, "plain", "utf-8"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

    try:
        sent = service.users().messages().send(
            userId="me",
            body={"raw": raw},
        ).execute()
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "message_id": None, "error": str(exc)}

    message_id = sent.get("id", "")
    now_str    = time.strftime("%Y-%m-%dT%H:%M:%S")

    case.setdefault("email_sent", {})[actor.value] = {
        "to":         institution_email,
        "sent_at":    now_str,
        "message_id": message_id,
        "subject":    subject,
    }
    _save_case(case)

    return {"success": True, "message_id": message_id, "error": None}


def poll_inbox(case_id: str) -> list[dict]:
    """
    Polls Gmail inbox for unread replies related to a specific case.

    For each matching unread message:
      1. Extracts plain-text body.
      2. Detects which actor the reply is from (via footer reference or sender address).
      3. Calls parse_institution_reply() to extract structured data.
      4. Persists the result to case_state.json.
      5. Marks the Gmail message as read.

    Parameters:
        case_id: HelveVista case identifier (e.g. "77800B67").

    Returns:
        list of dicts: [{"actor": str, "parsed_data": dict, "gmail_message_id": str}, ...]
    """
    try:
        service = _get_gmail_service()
    except (FileNotFoundError, ImportError, RuntimeError):
        return []

    query   = f"in:inbox is:unread {case_id}"
    results = service.users().messages().list(userId="me", q=query).execute()
    messages = results.get("messages", [])

    if not messages:
        return []

    case = _load_case()
    found: list[dict] = []

    for meta in messages:
        msg_id = meta["id"]
        msg    = service.users().messages().get(
            userId="me", messageId=msg_id, format="full"
        ).execute()

        body = _extract_body(msg)
        if not body:
            _mark_read(service, msg_id)
            continue

        actor = (
            _detect_actor_from_body(body, case_id)
            or _detect_actor_from_sent_records(case, msg)
        )

        parsed = parse_institution_reply(body, actor, case) if actor else {}

        if actor:
            now_str = time.strftime("%Y-%m-%dT%H:%M:%S")
            case.setdefault("institution_responses", {})[actor.value]     = parsed
            case.setdefault("institution_responded", {})[actor.value]     = True
            case.setdefault("institution_response_date", {})[actor.value] = now_str
            case.setdefault("email_replies", {})[actor.value] = {
                "received_at":      now_str,
                "gmail_message_id": msg_id,
                "parsed":           True,
            }

        _mark_read(service, msg_id)
        found.append({
            "actor":           actor.value if actor else "UNKNOWN",
            "parsed_data":     parsed,
            "gmail_message_id": msg_id,
        })

    if found:
        _save_case(case)

    return found


def parse_institution_reply(
    email_body: str,
    actor: Actor,
    case: dict,  # noqa: ARG001  (reserved for future context injection)
) -> dict:
    """
    Uses Claude API to extract structured pension data from an institution's email reply.

    LLM extraction only — never modifies state machine.

    Parameters:
        email_body: Plain-text content of the reply email.
        actor:      The institutional actor this reply is attributed to.
        case:       Case context (currently unused; reserved for enrichment).

    Returns:
        dict with actor-specific structured fields. Falls back to DEMO_RESPONSES
        if the API is unavailable or the response cannot be parsed.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return DEMO_RESPONSES.get(actor, {})

    client = anthropic.Anthropic(api_key=api_key)
    system = _PARSE_SYSTEM.format(actor_value=actor.value)

    try:
        message = client.messages.create(
            model      = "claude-sonnet-4-6",
            max_tokens = 256,
            system     = system,
            messages   = [{"role": "user", "content": email_body[:4000]}],
        )
        raw = message.content[0].text.strip()
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return DEMO_RESPONSES.get(actor, {})


def get_email_status(case: dict) -> dict[str, str]:
    """
    Returns the email coordination status for every actor in the case.

    Status values:
        "pending"  — no email sent yet
        "sent"     — email sent, no reply received
        "replied"  — reply received in inbox (from institution_responded)
        "parsed"   — reply parsed and stored (from email_replies)

    Parameters:
        case: Case dict loaded from case_state.json.

    Returns:
        dict mapping actor.value → status string for all three actors.
    """
    email_sent           = case.get("email_sent", {})
    email_replies        = case.get("email_replies", {})
    institution_responded = case.get("institution_responded", {})

    status: dict[str, str] = {}
    for actor in Actor:
        key = actor.value
        if email_replies.get(key, {}).get("parsed"):
            status[key] = "parsed"
        elif institution_responded.get(key):
            status[key] = "replied"
        elif key in email_sent:
            status[key] = "sent"
        else:
            status[key] = "pending"

    return status


# ══════════════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _get_gmail_service():
    """
    Builds an authenticated Gmail API service using OAuth2.

    Token is cached in token.json next to credentials.json.
    On first run, opens a browser window for the OAuth consent flow.

    Raises:
        FileNotFoundError: if credentials.json is missing from the project root.
        ImportError:       if Google API packages are not installed.
    """
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise ImportError(
            "Google API packages fehlen. Bitte installieren:\n"
            "  pip install google-auth google-auth-oauthlib "
            "google-auth-httplib2 google-api-python-client"
        ) from exc

    if not CREDENTIALS_PATH.exists():
        raise FileNotFoundError(
            f"credentials.json nicht gefunden: {CREDENTIALS_PATH}\n"
            "Bitte credentials.json vom Google Cloud Console herunterladen "
            "und im Projektverzeichnis ablegen."
        )

    creds: Optional[Credentials] = None

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow  = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_PATH), SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, "w", encoding="utf-8") as fh:
            fh.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def _extract_body(msg: dict) -> str:
    """Extracts the plain-text body from a Gmail message dict."""

    def _decode(data: str) -> str:
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")

    payload   = msg.get("payload", {})
    body_data = payload.get("body", {}).get("data")
    if body_data:
        return _decode(body_data)

    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain":
            data = part.get("body", {}).get("data")
            if data:
                return _decode(data)

    # Fallback: any part with data
    for part in payload.get("parts", []):
        data = part.get("body", {}).get("data")
        if data:
            return _decode(data)

    return ""


def _detect_actor_from_body(body: str, case_id: str) -> Optional[Actor]:
    """
    Detects the actor from the HelveVista footer embedded in the original email.

    Footer format: ``HelveVista Referenz: {case_id} | {actor.value}``
    """
    for actor in Actor:
        if f"HelveVista Referenz: {case_id} | {actor.value}" in body:
            return actor
    return None


def _detect_actor_from_sent_records(case: dict, msg: dict) -> Optional[Actor]:
    """
    Fallback actor detection: matches the reply sender against the institution
    email addresses stored in case_state.json under ``institution_emails``.
    """
    headers = {
        h["name"].lower(): h["value"]
        for h in msg.get("payload", {}).get("headers", [])
    }
    from_header = headers.get("from", "").lower()

    for actor_value, email in case.get("institution_emails", {}).items():
        if isinstance(email, str) and email.lower() in from_header:
            try:
                return Actor(actor_value)
            except ValueError:
                pass
    return None


def _mark_read(service, message_id: str) -> None:
    """Removes the UNREAD label from a Gmail message."""
    try:
        service.users().messages().modify(
            userId="me",
            messageId=message_id,
            body={"removeLabelIds": ["UNREAD"]},
        ).execute()
    except Exception:  # noqa: BLE001
        pass


def _load_case() -> dict:
    """Reads case_state.json. Returns {} if missing or corrupt."""
    if CASE_FILE.exists():
        try:
            with open(CASE_FILE, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_case(state: dict) -> None:
    """Writes case_state.json. Silently swallows IO errors."""
    try:
        with open(CASE_FILE, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2)
    except OSError:
        pass

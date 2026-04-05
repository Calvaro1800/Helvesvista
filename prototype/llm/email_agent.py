"""
llm/email_agent.py
------------------
Gmail-based agentic email bridge for HelveVista.

Solves the Cold Start Problem: institutions NOT on HelveVista can still
receive and respond to requests via structured email.

RÔLE AUTORISÉ (Modèle V2, §11):
    ✅ Send structured emails to institutions via Gmail API
    ✅ Poll inbox for replies per case + actor
    ✅ Parse institution replies using Claude API
    ✅ Return email status for UI display

RÔLE INTERDIT (Modèle V2, §11):
    ❌ Change any state in the state machine
    ❌ Influence transition logic
    ❌ Make final decisions
    ❌ Access the event log directly

PROVIDER: Gmail API (OAuth2) + Anthropic Claude API
"""

from __future__ import annotations

import base64
import json
import os
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

import anthropic

from core.states import Actor


# ── Paths ──────────────────────────────────────────────────────────────────────

PROJECT_ROOT     = Path(__file__).parent.parent.parent
CREDENTIALS_PATH = PROJECT_ROOT / "credentials.json"
TOKEN_PATH       = PROJECT_ROOT / "token.json"
CASE_FILE        = PROJECT_ROOT / "case_state.json"


# ── Gmail OAuth2 scopes ────────────────────────────────────────────────────────

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]

SENDER_ADDRESS = "info.helvevista@gmail.com"
SENDER_DISPLAY = "HelveVista Koordination"


# ── Actor labels ───────────────────────────────────────────────────────────────

ACTOR_LABELS: dict[str, str] = {
    Actor.OLD_PK.value: "Alte Pensionskasse",
    Actor.NEW_PK.value: "Neue Pensionskasse",
    Actor.AVS.value:    "AHV-Ausgleichskasse",
}


# ── Demo fallback responses ────────────────────────────────────────────────────
#
# Used when parse_institution_reply() cannot reach the Claude API
# or when the email body yields no parseable JSON.

DEMO_RESPONSES: dict[str, dict] = {
    Actor.OLD_PK.value: {
        "freizuegigkeit_chf": 45_200,
        "austrittsdatum":     "31.03.2025",
        "status":             "Austritt bestätigt",
    },
    Actor.NEW_PK.value: {
        "eintrittsdatum":         "01.04.2025",
        "bvg_koordinationsabzug": 26_460,
        "bvg_pflicht":            True,
    },
    Actor.AVS.value: {
        "ik_auszug":     "verfügbar",
        "beitragsjahre": 12,
        "luecken":       0,
    },
}


# ── Email body templates ───────────────────────────────────────────────────────

_PROFILE_CARD = """\
─────────────────────────────────────────
ANGABEN ZUR VERSICHERTEN PERSON
Name:       {user_name}
E-Mail:     {user_email}
Fall-ID:    {case_id}
Verfahren:  {verfahren}
─────────────────────────────────────────

MITTEILUNG DES VERSICHERTEN:
"{user_situation}"

"""

_REPLY_OPTIONS = """
────────────────────────────────────────────────────
ANTWORTMÖGLICHKEITEN:

Option A — Per E-Mail:
Antworten Sie direkt auf diese E-Mail mit den angeforderten Angaben.
Die Referenz-ID am Ende dieser E-Mail ermöglicht die automatische Zuordnung.

Option B — Via HelveVista Plattform:
Melden Sie sich unter http://localhost:8501 an und verwenden Sie
die Fall-ID {case_id} um diesen Fall direkt in der Plattform zu bearbeiten.
────────────────────────────────────────────────────
"""

_EMAIL_BODIES: dict[str, str] = {
    Actor.OLD_PK.value: """\
Sehr geehrte Damen und Herren

Im Auftrag von {user_name} wenden wir uns mit folgendem Anliegen an Sie.

""" + _PROFILE_CARD + """\
{user_name} tritt in Kürze aus Ihrem Versichertenbestand aus und wechselt zu \
einem neuen Arbeitgeber. Im Rahmen dieses Stellenwechsels ist die Abwicklung \
der Freizügigkeitsleistung gemäss Freizügigkeitsgesetz (FZG) erforderlich.

Wir bitten Sie um folgende Informationen:
  • Höhe des Freizügigkeitsguthabens zum Austrittsdatum
  • Austrittsdatum
  • Bestätigung der Überweisungsadresse für die neue Pensionskasse
""" + _REPLY_OPTIONS + """
Mit freundlichen Grüssen
HelveVista Koordinationsstelle
""",
    Actor.NEW_PK.value: """\
Sehr geehrte Damen und Herren

Im Auftrag von {user_name} wenden wir uns mit folgendem Anliegen an Sie.

""" + _PROFILE_CARD + """\
{user_name} wird in Kürze in Ihrem Unternehmen eintreten. Im Rahmen dieses \
Stellenwechsels sind die Anmeldung zur BVG-Pflicht sowie die Übernahme des \
Freizügigkeitsguthabens von der bisherigen Pensionskasse zu regeln.

Wir bitten Sie um folgende Informationen:
  • Eintrittsdatum
  • Geltender BVG-Koordinationsabzug
  • Bestätigung der BVG-Pflicht
""" + _REPLY_OPTIONS + """
Mit freundlichen Grüssen
HelveVista Koordinationsstelle
""",
    Actor.AVS.value: """\
Sehr geehrte Damen und Herren

Im Auftrag von {user_name} wenden wir uns mit folgendem Anliegen an Sie.

""" + _PROFILE_CARD + """\
{user_name} hat einen Stellenwechsel vollzogen und benötigt zur Überprüfung \
der Vorsorgesituation einen aktuellen IK-Auszug (Individuelle Kontenauszug).

Wir bitten Sie um folgende Informationen:
  • Aktueller IK-Auszug mit AHV-Beitragsjahren
  • Nachweis allfälliger Beitragslücken
""" + _REPLY_OPTIONS + """
Mit freundlichen Grüssen
HelveVista Koordinationsstelle
""",
}

# Footer appended to every outgoing email.
# The reference line is the anchor for reply detection.
_EMAIL_FOOTER = (
    "\n\n--- HelveVista Referenz: {case_id} | {actor_value} ---\n"
    "Diese E-Mail wurde automatisch durch das HelveVista Koordinationssystem generiert.\n"
    "Antworten Sie direkt auf diese E-Mail — "
    "die Referenz-ID ermöglicht die automatische Zuordnung.\n"
)


# ── Claude system prompt for reply parsing ─────────────────────────────────────

_PARSE_SYSTEM = """\
Du bist ein Vorsorge-Datenextraktor. Extrahiere aus dieser \
E-Mail-Antwort einer Schweizer Pensionskasse die relevanten Daten.
Akteur: {actor_value}
Antworte NUR als JSON:
- OLD_PK: freizuegigkeit_chf (int), austrittsdatum (str DD.MM.YYYY), \
status (str)
- NEW_PK: eintrittsdatum (str DD.MM.YYYY), \
bvg_koordinationsabzug (int), bvg_pflicht (bool)
- AVS: ik_auszug (str), beitragsjahre (int), luecken (int)
Nur JSON, kein Text.\
"""


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def get_gmail_service():
    """
    Returns an authenticated Gmail API service.

    Looks for credentials.json in the project root.
    If token.json exists and is valid → uses it directly.
    If not → runs InstalledAppFlow for browser-based OAuth consent.
    Saves token to token.json after first auth.

    Returns:
        Authenticated googleapiclient Resource object.

    Raises:
        FileNotFoundError: if credentials.json is missing.
        ImportError:       if Google API packages are not installed.
        RuntimeError:      if the OAuth flow fails.
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

    creds: Optional[object] = None

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


def send_institution_email(
    actor: Actor,
    case: dict,
    institution_email: str,
) -> bool:
    """
    Sends a structured coordination email from info.helvevista@gmail.com
    to the given institution.

    Does NOT modify the orchestrator state machine — only persists a send
    record to case_state.json under ``email_sent[actor.value]``.

    Parameters:
        actor:              Institutional actor (OLD_PK, NEW_PK, AVS).
        case:               Case dict loaded from case_state.json.
        institution_email:  Recipient address (e.g. "info@assepro.ch").

    Returns:
        True on success, False on failure.
    """
    try:
        service = get_gmail_service()
    except (FileNotFoundError, ImportError, RuntimeError) as exc:
        import traceback
        traceback.print_exc()
        _record_email_error(case, actor.value, str(exc))
        return False

    case_id        = case.get("case_id", "UNKNOWN")
    user_name      = case.get("user_name", "Versicherter")
    user_email     = case.get("user_email", case.get("email", ""))
    user_situation = case.get("situation", case.get("user_message", ""))
    verfahren      = case.get("verfahren", "Stellenwechsel")
    label          = ACTOR_LABELS.get(actor.value, actor.value)
    subject        = (
        f"HelveVista \u2014 Anfrage {label} \u2014 Fall {case_id[:8]}"
    )

    body = (
        _EMAIL_BODIES[actor.value].format(
            user_name=user_name,
            user_email=user_email,
            user_situation=user_situation,
            case_id=case_id,
            verfahren=verfahren,
        )
        + _EMAIL_FOOTER.format(case_id=case_id, actor_value=actor.value)
    )

    msg = MIMEMultipart("alternative")
    msg["From"]    = f"{SENDER_DISPLAY} <{SENDER_ADDRESS}>"
    msg["To"]      = institution_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    try:
        sent = service.users().messages().send(
            userId="me",
            body={"raw": raw},
        ).execute()
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        _record_email_error(case, actor.value, str(exc))
        return False

    message_id = sent.get("id", "")
    now_str    = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    case.setdefault("email_sent", {})[actor.value] = {
        "to":         institution_email,
        "sent_at":    now_str,
        "message_id": message_id,
        "subject":    subject,
        "error":      False,
    }
    _save_case(case)
    return True


def send_followup_email(
    institution_email: str,
    subject: str,
    body: str,
) -> bool:
    """
    Sends a free-text follow-up email (document request or question) from
    info.helvevista@gmail.com to the given institution via Gmail API.

    Does NOT modify the orchestrator state machine.

    Returns:
        True on success, False on failure.
    """
    try:
        service = get_gmail_service()
    except (FileNotFoundError, ImportError, RuntimeError) as exc:
        import traceback
        traceback.print_exc()
        return False

    msg = MIMEMultipart("alternative")
    msg["From"]    = f"{SENDER_DISPLAY} <{SENDER_ADDRESS}>"
    msg["To"]      = institution_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    try:
        sent = service.users().messages().send(
            userId="me",
            body={"raw": raw},
        ).execute()
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        return False

    return True


def poll_inbox(case_id: str, actor_value: str) -> Optional[dict]:
    """
    Polls Gmail inbox for an unread reply to a specific case + actor.

    Search query: ``{case_id} {actor_value}`` in:inbox (no is:unread filter)

    Only processes emails whose internalDate is strictly after the
    ``sent_at`` timestamp recorded in ``case["email_sent"][actor_value]``,
    so pre-existing or already-read messages are never matched.

    For the first matching message:
      1. Extracts plain-text body.
      2. Calls parse_institution_reply() to extract structured data.
      3. Saves parsed data to case under institution_responses[actor_value].
      4. Marks the email as read.
      5. Saves case_state.json.

    Parameters:
        case_id:     HelveVista case identifier (e.g. "77800B67").
        actor_value: Actor enum value string (e.g. "OLD_PK").

    Returns:
        Parsed data dict if a reply was found and processed, None otherwise.
    """
    try:
        service = get_gmail_service()
    except (FileNotFoundError, ImportError, RuntimeError):
        return None

    query   = f"in:inbox {case_id} {actor_value}"
    results = service.users().messages().list(userId="me", q=query).execute()
    messages = results.get("messages", [])

    if not messages:
        return None

    case = _load_case()

    # Determine the earliest acceptable internalDate (ms since epoch).
    # Only process emails received AFTER the send_at timestamp so that
    # old or pre-existing messages are never mistakenly matched.
    sent_at_str = (
        case.get("email_sent", {})
            .get(actor_value, {})
            .get("sent_at", "")
    )
    min_internal_date_ms: int = 0
    if sent_at_str:
        try:
            sent_dt = datetime.fromisoformat(sent_at_str.replace("Z", "+00:00"))
            min_internal_date_ms = int(sent_dt.timestamp() * 1000)
        except ValueError:
            pass

    for meta in messages:
        msg_id = meta["id"]
        msg    = service.users().messages().get(
            userId="me", id=msg_id, format="full"
        ).execute()

        # Skip emails that arrived before (or at) the time we sent our request.
        internal_date_ms = int(msg.get("internalDate", "0"))
        if internal_date_ms <= min_internal_date_ms:
            continue

        body = _extract_body(msg)
        _mark_read(service, msg_id)

        if not body:
            continue

        parsed = parse_institution_reply(body, actor_value, case)
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

        case.setdefault("institution_responses", {})[actor_value]     = parsed
        case.setdefault("institution_responded", {})[actor_value]     = True
        case.setdefault("institution_response_date", {})[actor_value] = now_str
        case.setdefault("email_replies", {})[actor_value] = {
            "received_at":       now_str,
            "gmail_message_id":  msg_id,
            "parsed":            True,
        }
        _save_case(case)
        return parsed

    return None


def parse_institution_reply(
    email_body: str,
    actor_value: str,
    case: dict,  # noqa: ARG001  (reserved for future context injection)
) -> dict:
    """
    Uses Claude API to extract structured pension data from an institution's
    email reply.

    LLM extraction only — never modifies state machine.

    Parameters:
        email_body:  Plain-text content of the reply email.
        actor_value: Actor enum value string (e.g. "OLD_PK").
        case:        Case context (reserved for future enrichment).

    Returns:
        dict with actor-specific structured fields. Falls back to
        DEMO_RESPONSES if the API is unavailable or unparseable.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"raw_reply": email_body}

    client = anthropic.Anthropic(api_key=api_key)
    system = _PARSE_SYSTEM.format(actor_value=actor_value)

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
        return {"raw_reply": email_body}


def poll_followup_inbox(
    case: dict,
    actor_value: str,
    followup_type: str,
) -> Optional[str]:
    """
    Polls Gmail inbox for a reply to a follow-up email (dokument or rueckfrage).

    Search query: ``in:inbox {case_id} {actor_value} {followup_type}``

    Only processes emails whose internalDate is strictly after the sent_at
    timestamp so pre-existing messages are never matched.

    Stores result in case under follow_up_replies[actor_value][followup_type]:
        {"reply_text": str, "received_at": ISO timestamp, "gmail_message_id": str}

    Saves case_state.json after storing.

    Parameters:
        case:          Case dict loaded from case_state.json.
        actor_value:   Actor enum value string (e.g. "OLD_PK").
        followup_type: "dokument" or "rueckfrage".

    Returns:
        Reply text if found, None otherwise.
    """
    try:
        service = get_gmail_service()
    except (FileNotFoundError, ImportError, RuntimeError):
        return None

    case_id = case.get("case_id", "UNKNOWN")
    query   = f"in:inbox {case_id}"
    results = service.users().messages().list(userId="me", q=query).execute()
    messages = results.get("messages", [])

    if not messages:
        return None

    # Determine earliest acceptable internalDate from the send timestamp.
    min_internal_date_ms: int = 0
    if followup_type == "dokument":
        sent_at_str = (
            case.get("follow_up_requests", {})
                .get(actor_value, {})
                .get("sent_at", "")
        )
    else:  # rueckfrage
        questions   = case.get("follow_up_questions", {}).get(actor_value, [])
        sent_at_str = questions[-1]["sent_at"] if questions else ""

    if sent_at_str:
        try:
            sent_dt = datetime.fromisoformat(sent_at_str.replace("Z", "+00:00"))
            min_internal_date_ms = int(sent_dt.timestamp() * 1000)
        except ValueError:
            pass

    for meta in messages:
        msg_id = meta["id"]
        msg    = service.users().messages().get(
            userId="me", id=msg_id, format="full"
        ).execute()

        internal_date_ms = int(msg.get("internalDate", "0"))
        if internal_date_ms <= min_internal_date_ms:
            continue

        body = _extract_body(msg)
        _mark_read(service, msg_id)

        if not body:
            continue

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        case.setdefault("follow_up_replies", {}).setdefault(actor_value, {})[followup_type] = {
            "reply_text":       body,
            "received_at":      now_str,
            "gmail_message_id": msg_id,
        }
        _save_case(case)
        return body

    return None


def get_followup_status(case: dict, actor_value: str, followup_type: str) -> str:
    """
    Returns the follow-up email status for a specific actor and follow-up type.

    Status values:
        "not_sent" — no follow-up email sent yet
        "sent"     — follow-up sent, waiting for reply
        "replied"  — reply received

    Parameters:
        case:          Case dict loaded from case_state.json.
        actor_value:   Actor enum value string (e.g. "OLD_PK").
        followup_type: "dokument" or "rueckfrage".

    Returns:
        One of "not_sent", "sent", "replied".
    """
    if case.get("follow_up_replies", {}).get(actor_value, {}).get(followup_type):
        return "replied"

    if followup_type == "dokument":
        if actor_value in case.get("follow_up_requests", {}):
            return "sent"
    else:  # rueckfrage
        if case.get("follow_up_questions", {}).get(actor_value):
            return "sent"

    return "not_sent"


def get_email_status(case: dict, actor_value: str) -> str:
    """
    Returns the email coordination status for a specific actor.

    Status values:
        "not_sent"  — no email sent yet
        "sent"      — email sent, waiting for reply
        "replied"   — reply received and parsed
        "error"     — send failed

    Parameters:
        case:        Case dict loaded from case_state.json.
        actor_value: Actor enum value string (e.g. "OLD_PK").

    Returns:
        One of "not_sent", "sent", "replied", "error".
    """
    email_replies = case.get("email_replies", {})
    email_sent    = case.get("email_sent", {})

    if email_replies.get(actor_value, {}).get("parsed"):
        return "replied"

    sent_rec = email_sent.get(actor_value)
    if sent_rec is None:
        return "not_sent"
    if sent_rec.get("error"):
        return "error"
    return "sent"


# ══════════════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _record_email_error(case: dict, actor_value: str, error_msg: str) -> None:
    """Persists a send failure record so get_email_status() returns 'error'."""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    case.setdefault("email_sent", {})[actor_value] = {
        "to":         "",
        "sent_at":    now_str,
        "message_id": "",
        "subject":    "",
        "error":      True,
        "error_msg":  error_msg,
    }
    _save_case(case)


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

    # Fallback: any part with body data
    for part in payload.get("parts", []):
        data = part.get("body", {}).get("data")
        if data:
            return _decode(data)

    return ""


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
    """Writes case_state.json atomically. Silently swallows IO errors."""
    try:
        with open(CASE_FILE, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2)
    except OSError:
        pass

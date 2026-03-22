# SKILL — Email Simulation for HelveVista

## Overview

This skill defines how to simulate orchestrated emails between HelveVista
and institutional actors (OLD_PK, NEW_PK, AVS).

No real SMTP or email sending. Everything is simulated and displayed in the UI.
The goal is to demonstrate the communication flow for H3 evaluation and
for Alexandre's requirement of «orchestrated and simplified email exchange».

---

## Concept

Each actor interaction in HelveVista generates two simulated emails:
1. **Outgoing** — HelveVista → Institution (request)
2. **Incoming** — Institution → HelveVista (response)

These emails are stored in the Event Log as events and displayed in the UI.

---

## Email Templates

### Outgoing — HelveVista to Institution

```python
EMAIL_TEMPLATES_OUTGOING = {
    "STELLENWECHSEL": {
        Actor.OLD_PK: {
            "subject": "Freizügigkeitsabrechnung — Stellenwechsel per {date}",
            "body": """
Sehr geehrte Damen und Herren,

Im Auftrag von {user_name} teilen wir Ihnen mit, dass ein Stellenwechsel
per {exit_date} stattfindet.

Wir bitten Sie um folgende Unterlagen:
- Freizügigkeitsabrechnung per Austrittsdatum
- Austrittsbestätigung mit Guthaben per {exit_date}

Bitte antworten Sie bis {deadline} auf diese Nachricht.

Mit freundlichen Grüssen
HelveVista — Digitaler Vorsorgevermittler
            """.strip()
        },
        Actor.NEW_PK: {
            "subject": "Eintrittsanmeldung BVG — Stellenwechsel per {date}",
            "body": """
Sehr geehrte Damen und Herren,

Im Auftrag von {user_name} melden wir den Eintritt per {entry_date} an.

Wir bitten Sie um:
- Bestätigung der BVG-Pflicht ab Eintrittsdatum
- Angabe des Koordinationsabzugs und Versicherungsplans
- Instruktionen für die Freizügigkeitsüberweisung

Bitte antworten Sie bis {deadline}.

Mit freundlichen Grüssen
HelveVista — Digitaler Vorsorgevermittler
            """.strip()
        },
        Actor.AVS: {
            "subject": "IK-Auszug Anfrage — {user_name}",
            "body": """
Sehr geehrte Damen und Herren,

Im Auftrag von {user_name} bitten wir um einen aktuellen
Individuellen Kontenauszug (IK-Auszug).

Zweck: Überprüfung der Beitragsjahre im Rahmen eines Stellenwechsels.

Bitte antworten Sie bis {deadline}.

Mit freundlichen Grüssen
HelveVista — Digitaler Vorsorgevermittler
            """.strip()
        }
    }
}
```

### Incoming — Institution to HelveVista (simulated)

```python
EMAIL_TEMPLATES_INCOMING = {
    Actor.OLD_PK: {
        "subject": "Re: Freizügigkeitsabrechnung — Bestätigung",
        "body": """
Sehr geehrte Damen und Herren,

Wir bestätigen den Austritt von {user_name} per {exit_date}.

Freizügigkeitsguthaben: CHF {freizuegigkeit_chf:,.0f}
Austrittsbestätigung: beiliegend

Das Guthaben wird auf Anweisung an die neue Pensionskasse überwiesen.

Mit freundlichen Grüssen
{institution_name}
        """.strip()
    },
    Actor.NEW_PK: {
        "subject": "Re: Eintrittsanmeldung BVG — Bestätigung",
        "body": """
Sehr geehrte Damen und Herren,

Wir bestätigen den Eintritt von {user_name} per {entry_date}.

BVG-Koordinationsabzug: CHF {bvg_koordinationsabzug:,.0f}
Versicherungspflicht: ab Eintrittsdatum

Bitte überweisen Sie das Freizügigkeitsguthaben auf folgendes Konto:
IBAN: CH00 0000 0000 0000 0000 0 (simuliert)

Mit freundlichen Grüssen
{institution_name}
        """.strip()
    },
    Actor.AVS: {
        "subject": "Re: IK-Auszug — {user_name}",
        "body": """
Sehr geehrte Damen und Herren,

Beiliegend finden Sie den IK-Auszug für {user_name}.

Beitragsjahre: {beitragsjahre}
Lücken: {luecken}
Auszug gültig per: {date}

Mit freundlichen Grüssen
AHV-Ausgleichskasse
        """.strip()
    }
}
```

---

## Email Generator

```python
from datetime import datetime, timedelta

def generate_outgoing_email(actor: Actor, use_case: str, context: dict) -> dict:
    """Generate a simulated outgoing email for an actor request."""
    template = EMAIL_TEMPLATES_OUTGOING.get(use_case, {}).get(actor)
    if not template:
        return {}

    deadline = (datetime.now() + timedelta(days=14)).strftime("%d.%m.%Y")

    body = template["body"].format(
        user_name=context.get("user_name", "der versicherten Person"),
        date=context.get("date", datetime.now().strftime("%d.%m.%Y")),
        exit_date=context.get("exit_date", "31.03.2025"),
        entry_date=context.get("entry_date", "01.04.2025"),
        deadline=deadline,
    )

    subject = template["subject"].format(
        date=context.get("date", datetime.now().strftime("%d.%m.%Y")),
        user_name=context.get("user_name", "Versicherter"),
    )

    return {
        "direction": "OUTGOING",
        "actor": actor.value,
        "subject": subject,
        "body": body,
        "timestamp": datetime.now().isoformat(),
        "status": "SENT"
    }


def generate_incoming_email(actor: Actor, response_data: dict, context: dict) -> dict:
    """Generate a simulated incoming response email from an institution."""
    template = EMAIL_TEMPLATES_INCOMING.get(actor)
    if not template:
        return {}

    body = template["body"].format(
        user_name=context.get("user_name", "der versicherten Person"),
        exit_date=context.get("exit_date", "31.03.2025"),
        entry_date=context.get("entry_date", "01.04.2025"),
        institution_name=actor.value,
        date=datetime.now().strftime("%d.%m.%Y"),
        **response_data
    )

    return {
        "direction": "INCOMING",
        "actor": actor.value,
        "subject": template["subject"].format(
            user_name=context.get("user_name", "Versicherter")
        ),
        "body": body,
        "timestamp": datetime.now().isoformat(),
        "status": "RECEIVED"
    }
```

---

## Displaying Emails in Streamlit

```python
def render_email(email: dict):
    """Render a single simulated email in the UI."""
    direction_icon = "📤" if email["direction"] == "OUTGOING" else "📥"
    direction_label = "Gesendet" if email["direction"] == "OUTGOING" else "Empfangen"

    with st.expander(f"{direction_icon} {email['subject']} — {direction_label}"):
        col1, col2 = st.columns([3, 1])
        with col1:
            st.caption(f"Institution: {email['actor']}")
        with col2:
            st.caption(email['timestamp'][:10])
        st.text(email['body'])


def render_email_thread(emails: list):
    """Render all emails as a thread."""
    st.subheader("📬 Kommunikationsprotokoll")
    st.caption("Alle Nachrichten zwischen HelveVista und den Institutionen")

    for email in sorted(emails, key=lambda e: e['timestamp']):
        render_email(email)
```

---

## Integration with Event Log

```python
# Store emails as events in the Event Log
def log_email_event(event_log, email: dict):
    event_log.append({
        "type": "EMAIL_SIMULATION",
        "direction": email["direction"],
        "actor": email["actor"],
        "subject": email["subject"],
        "timestamp": email["timestamp"]
    })
```

---

## What NOT to do

- ❌ Never send real emails — simulation only
- ❌ Never use real personal data in email templates
- ❌ Never store email content in the core EventLog as primary data
- ❌ Never block UI while generating emails — they are instant
- ❌ Never show raw JSON email data to end users — always use render_email()

"""
core/event_log.py
-----------------
Event Log append-only — Source of Truth du système HelveVista.

PRINCIPE (Modèle V2, §5) :
    - Chaque changement d'état génère un événement immuable.
    - L'état courant est une VUE DÉRIVÉE du log, pas une source primaire.
    - Tout état du système est causalement reconstructible depuis le log.

    Event Log = Source of Truth
    State     = vue dérivée
"""

import uuid
import json
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Any, Optional
from pathlib import Path


@dataclass(frozen=True)
class Event:
    """
    Événement immuable du système.
    (Modèle V2, §5 : case_id, actor, timestamp, version, payload_reference)
    """
    event_id:   str
    case_id:    str
    actor:      str           # "ORCHESTRATOR" ou nom d'acteur institutionnel
    event_type: str           # ex. "STATE_TRANSITION", "VERSION_CONFLICT", "HITL_REQUIRED"
    timestamp:  str           # ISO 8601 UTC
    version:    int           # version du cas au moment de l'événement
    payload:    dict          # données associées (état avant/après, motif, etc.)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


class EventLog:
    """
    Log append-only. Aucune modification d'événement existant n'est permise.
    """

    def __init__(self, case_id: str, persist_path: Optional[Path] = None):
        self.case_id      = case_id
        self._events: list[Event] = []
        self._version     = 0
        self._persist_path = persist_path

    # ── API publique ─────────────────────────────────────────────────────────

    def append(
        self,
        actor:      str,
        event_type: str,
        payload:    dict
    ) -> Event:
        """
        Ajoute un événement immuable au log.
        Incrémente la version du cas.
        """
        self._version += 1
        event = Event(
            event_id   = str(uuid.uuid4()),
            case_id    = self.case_id,
            actor      = actor,
            event_type = event_type,
            timestamp  = datetime.now(timezone.utc).isoformat(),
            version    = self._version,
            payload    = payload,
        )
        self._events.append(event)

        if self._persist_path:
            self._write_to_disk(event)

        return event

    @property
    def current_version(self) -> int:
        return self._version

    @property
    def events(self) -> list[Event]:
        """Retourne une copie immuable du log."""
        return list(self._events)

    def events_for_actor(self, actor: str) -> list[Event]:
        return [e for e in self._events if e.actor == actor]

    def last_event(self) -> Optional[Event]:
        return self._events[-1] if self._events else None

    # ── Versionsprüfung (Modèle V2, §5.1) ──────────────────────────────────

    def check_response_version(self, response_version: int) -> bool:
        """
        Vérifie si une réponse institutionnelle est encore valide.

        Retourne True  si response_version == current_version  (valide)
        Retourne False si response_version <  current_version  (CONFLICT_DETECTED)

        (Modèle V2, §5.1)
        """
        return response_version >= self._version

    # ── Sérialisation ────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "case_id":         self.case_id,
            "current_version": self._version,
            "event_count":     len(self._events),
            "events":          [e.to_dict() for e in self._events],
        }

    def _write_to_disk(self, event: Event):
        """Persistence ligne par ligne (JSON Lines format)."""
        with open(self._persist_path, "a", encoding="utf-8") as f:
            f.write(event.to_json() + "\n")

    def summary(self) -> str:
        lines = [f"EventLog — case_id={self.case_id} | version={self._version} | events={len(self._events)}"]
        for e in self._events:
            lines.append(f"  [{e.version:03d}] {e.timestamp[:19]}Z  {e.actor:<20} {e.event_type}  {e.payload}")
        return "\n".join(lines)

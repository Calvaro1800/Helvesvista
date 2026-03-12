"""
core/actor_process.py
---------------------
Mini-state-machine pour un acteur institutionnel.

Chaque acteur (OLD_PK, NEW_PK, AVS) possède sa propre instance.
Les sous-processus tournent de façon PARALLÈLE et ASYNCHRONE.

(Modèle V2, §3.2 et §4)

RÈGLE : Ce module ne contient AUCUNE logique LLM.
        Toute transition est déterministe.
"""

import time
from dataclasses import dataclass, field
from typing import Optional, Callable

from .states import Actor, ActorState, TERMINAL_ACTOR_STATES
from .event_log import EventLog


# ── Configuration par acteur ─────────────────────────────────────────────────

@dataclass
class ActorConfig:
    actor:           Actor
    is_optional:     bool  = False   # AVS = True (Modèle V2, §8)
    timeout_seconds: float = 10.0    # délai avant TIMEOUT (simulé)
    max_retries:     int   = 2       # retries max avant ESCALATED (Modèle V2, §7)


DEFAULT_CONFIGS = {
    Actor.OLD_PK: ActorConfig(actor=Actor.OLD_PK, is_optional=False, timeout_seconds=10.0, max_retries=2),
    Actor.NEW_PK: ActorConfig(actor=Actor.NEW_PK, is_optional=False, timeout_seconds=10.0, max_retries=2),
    Actor.AVS:    ActorConfig(actor=Actor.AVS,    is_optional=True,  timeout_seconds=8.0,  max_retries=1),
}


# ── Mini-state-machine ───────────────────────────────────────────────────────

class ActorProcess:
    """
    Sous-processus déterministe pour un acteur institutionnel.

    Cycle de vie standard :
        PENDING → REQUEST_SENT → WAITING → RESPONSE_RECEIVED → COMPLETED

    Avec gestion d'erreurs :
        WAITING → TIMEOUT → (retry) → WAITING
                          → (retries épuisés) → ESCALATED

        RESPONSE_RECEIVED → CONFLICT_DETECTED → HITL_REQUIRED
                                              → (résolu) → COMPLETED
                                              → (abandonné) → ESCALATED
    """

    def __init__(
        self,
        config:    ActorConfig,
        event_log: EventLog,
        activated: bool = True,
    ):
        self.config    = config
        self.actor     = config.actor
        self.log       = event_log
        self._state    = ActorState.SKIPPED if not activated else ActorState.PENDING
        self._retries  = 0
        self._request_time: Optional[float] = None
        self._pending_response: Optional[dict] = None

        if not activated:
            self.log.append(
                actor      = self.actor.value,
                event_type = "ACTOR_SKIPPED",
                payload    = {"reason": "not activated in conditional fork"},
            )

    # ── Propriétés ──────────────────────────────────────────────────────────

    @property
    def state(self) -> ActorState:
        return self._state

    @property
    def is_terminal(self) -> bool:
        return self._state in TERMINAL_ACTOR_STATES

    @property
    def name(self) -> str:
        return self.actor.value

    # ── Transitions déterministes ────────────────────────────────────────────

    def send_request(self, request_payload: dict) -> None:
        """
        Transition : PENDING → REQUEST_SENT → WAITING
        Enregistre l'heure d'envoi pour le mécanisme de Timeout.
        """
        self._assert_state(ActorState.PENDING)
        self._transition(ActorState.REQUEST_SENT, payload={
            "request": request_payload,
        })
        self._request_time = time.monotonic()
        self._transition(ActorState.WAITING, payload={
            "timeout_seconds": self.config.timeout_seconds,
            "retries_remaining": self.config.max_retries - self._retries,
        })

    def receive_response(self, response: dict, response_version: int) -> None:
        """
        Transition : WAITING → RESPONSE_RECEIVED
        Déclenche la Versionsprüfung (Modèle V2, §5.1).
        Si version obsolète → CONFLICT_DETECTED.
        Sinon → COMPLETED.
        """
        self._assert_state(ActorState.WAITING)

        # ── Versionsprüfung AVANT tout log (Modèle V2, §5.1) ────────────────
        # La vérification doit se faire sur la version courante du log
        # AVANT d'ajouter de nouveaux événements.
        version_valid = self.log.check_response_version(response_version)
        current_v     = self.log.current_version

        self._transition(ActorState.RESPONSE_RECEIVED, payload={
            "response":         response,
            "response_version": response_version,
            "version_valid":    version_valid,
        })

        if not version_valid:
            self._transition(ActorState.CONFLICT_DETECTED, payload={
                "response_version": response_version,
                "current_version":  current_v,
                "reason": "response_version < current_data_version — données obsolètes",
            })
            self._transition(ActorState.HITL_REQUIRED, payload={
                "message": "Intervention humaine requise pour résoudre le conflit de version.",
            })
        else:
            self._transition(ActorState.COMPLETED, payload={
                "response": response,
            })

    def check_timeout(self) -> bool:
        """
        Vérifie si le délai d'attente est dépassé.
        À appeler périodiquement depuis l'orchestrateur.
        Retourne True si un TIMEOUT a été déclenché.
        """
        if self._state != ActorState.WAITING:
            return False
        if self._request_time is None:
            return False

        elapsed = time.monotonic() - self._request_time
        if elapsed >= self.config.timeout_seconds:
            self._handle_timeout(elapsed)
            return True
        return False

    def resolve_conflict(self, resolution: dict) -> None:
        """
        Transition : HITL_REQUIRED → COMPLETED (si résolu)
        Appelé après intervention humaine.
        """
        self._assert_state(ActorState.HITL_REQUIRED)
        self._transition(ActorState.COMPLETED, payload={
            "resolution": resolution,
            "resolved_by": "human_in_the_loop",
        })

    def abort_conflict(self) -> None:
        """
        Transition : HITL_REQUIRED → ESCALATED (si abandonné)
        """
        self._assert_state(ActorState.HITL_REQUIRED)
        self._transition(ActorState.ESCALATED, payload={
            "reason": "conflict not resolved — escalated by user",
        })

    # ── Mécanisme Liveness (Modèle V2, §7) ──────────────────────────────────

    def _handle_timeout(self, elapsed: float) -> None:
        self._transition(ActorState.TIMEOUT, payload={
            "elapsed_seconds": round(elapsed, 2),
            "retry_attempt":   self._retries + 1,
            "max_retries":     self.config.max_retries,
        })

        if self._retries < self.config.max_retries:
            self._retries += 1
            # Reset pour retry
            self._request_time = time.monotonic()
            self._transition(ActorState.WAITING, payload={
                "retry_attempt":    self._retries,
                "timeout_seconds":  self.config.timeout_seconds,
            })
        else:
            # Liveness garantie : escalade pour éviter deadlock
            self._transition(ActorState.ESCALATED, payload={
                "reason": f"max retries ({self.config.max_retries}) épuisés — escalade automatique",
            })

    # ── Helpers internes ─────────────────────────────────────────────────────

    def _transition(self, new_state: ActorState, payload: dict) -> None:
        old_state  = self._state
        self._state = new_state
        self.log.append(
            actor      = self.actor.value,
            event_type = "STATE_TRANSITION",
            payload    = {
                "from":  old_state.value,
                "to":    new_state.value,
                **payload,
            },
        )

    def _assert_state(self, expected: ActorState) -> None:
        if self._state != expected:
            raise ValueError(
                f"[{self.name}] Transition invalide : état attendu={expected.value}, "
                f"état actuel={self._state.value}"
            )

    def __repr__(self) -> str:
        return f"ActorProcess({self.name}, state={self._state.value})"

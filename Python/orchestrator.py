"""
core/orchestrator.py
--------------------
Orchestrateur principal HelveVista.

Responsabilités :
    - Gérer l'état global du cas (OrchestratorState)
    - Exécuter le Conditional Fork (activation conditionnelle des acteurs)
    - Surveiller les sous-processus parallèles
    - Déclencher l'Aggregation quand tous les acteurs sont terminaux
    - Gérer USER_VALIDATION et les états finaux

RÈGLE FONDAMENTALE (Modèle V2, §11) :
    L'orchestrateur est 100% déterministe.
    Il appelle la couche LLM uniquement pour structurer / extraire / formuler.
    Il ne délègue JAMAIS une décision de transition au LLM.
"""

import uuid
from typing import Optional

from .states import (
    OrchestratorState, Actor, ActorState,
    TERMINAL_ACTOR_STATES, SUCCESSFUL_ACTOR_STATES
)
from .event_log import EventLog
from .actor_process import ActorProcess, ActorConfig, DEFAULT_CONFIGS


class HelveVistaOrchestrator:
    """
    Orchestrateur principal du système HelveVista.

    Use case : Stellenwechsel (alte PK, neue PK, AVS optionelle)
    """

    def __init__(self, case_id: Optional[str] = None):
        self.case_id   = case_id or str(uuid.uuid4())
        self.log       = EventLog(self.case_id)
        self._state    = OrchestratorState.INIT
        self._actors:  dict[Actor, ActorProcess] = {}
        self._case_context: dict = {}

        # Enregistrement de l'initialisation
        self.log.append(
            actor      = "ORCHESTRATOR",
            event_type = "CASE_INIT",
            payload    = {"case_id": self.case_id},
        )

    # ── Propriétés ──────────────────────────────────────────────────────────

    @property
    def state(self) -> OrchestratorState:
        return self._state

    @property
    def actors(self) -> dict[Actor, ActorProcess]:
        return dict(self._actors)

    # ── Flux principal ───────────────────────────────────────────────────────

    def structure_case(self, raw_input: str, structured_context: dict) -> None:
        """
        INIT → STRUCTURED

        Le contexte structuré est fourni par la couche LLM (llm/structurer.py).
        L'orchestrateur ne fait que l'enregistrer et avancer son état.

        Args:
            raw_input:          Saisie brute de l'utilisateur
            structured_context: Résultat de la structuration LLM
        """
        self._assert_state(OrchestratorState.INIT)
        self._case_context = structured_context
        self._transition(OrchestratorState.STRUCTURED, payload={
            "raw_input_length": len(raw_input),
            "actors_mentioned": structured_context.get("actors_involved", []),
            "use_case":         structured_context.get("use_case", "unknown"),
        })

    def execute_conditional_fork(self, activated_actors: set[Actor]) -> None:
        """
        STRUCTURED → CONDITIONAL_FORK → ORCHESTRATING

        Crée une mini-state-machine pour chaque acteur.
        Les acteurs non activés reçoivent l'état SKIPPED.

        (Modèle V2, §3.1 : activation conditionnelle)
        """
        self._assert_state(OrchestratorState.STRUCTURED)
        self._transition(OrchestratorState.CONDITIONAL_FORK, payload={
            "activated_actors": [a.value for a in activated_actors],
            "skipped_actors":   [a.value for a in set(Actor) - activated_actors],
        })

        # Instanciation des sous-processus
        for actor in Actor:
            config    = DEFAULT_CONFIGS[actor]
            activated = actor in activated_actors
            self._actors[actor] = ActorProcess(
                config    = config,
                event_log = self.log,
                activated = activated,
            )

        self._transition(OrchestratorState.ORCHESTRATING, payload={
            "active_processes": [a.value for a in activated_actors],
        })

    def send_actor_request(self, actor: Actor, request_payload: dict) -> None:
        """
        Envoie une requête à un acteur institutionnel spécifique.
        (Modèle V2, §4 : REQUEST_SENT)
        """
        self._assert_state(OrchestratorState.ORCHESTRATING)
        self._actors[actor].send_request(request_payload)

    def receive_actor_response(
        self,
        actor:            Actor,
        response:         dict,
        response_version: int,
    ) -> None:
        """
        Reçoit une réponse d'un acteur et déclenche la Versionsprüfung.
        (Modèle V2, §5.1)
        """
        self._assert_state(OrchestratorState.ORCHESTRATING)
        self._actors[actor].receive_response(response, response_version)
        self._check_aggregation_ready()

    def resolve_hitl(self, actor: Actor, resolution: dict) -> None:
        """
        Résout un conflit HITL_REQUIRED pour un acteur.
        (Modèle V2, §6 : Human-in-the-Loop)
        """
        self._actors[actor].resolve_conflict(resolution)
        self._check_aggregation_ready()

    def abort_hitl(self, actor: Actor) -> None:
        """Abandonne la résolution d'un conflit → ESCALATED."""
        self._actors[actor].abort_conflict()
        self._check_aggregation_ready()

    def tick(self) -> None:
        """
        Vérification périodique des Timeouts pour tous les acteurs actifs.
        À appeler régulièrement dans une boucle principale.
        (Modèle V2, §7 : Liveness-Mechanismen)
        """
        if self._state != OrchestratorState.ORCHESTRATING:
            return
        for process in self._actors.values():
            if not process.is_terminal:
                process.check_timeout()
        self._check_aggregation_ready()

    def validate_and_close(self, user_decision: str) -> None:
        """
        USER_VALIDATION → état final

        user_decision : "accept" | "escalate" | "abort"
        (Modèle V2, §9)
        """
        self._assert_state(OrchestratorState.USER_VALIDATION)

        final_state_map = {
            "accept":   OrchestratorState.CLOSED_SUCCESS,
            "escalate": OrchestratorState.CLOSED_ESCALATED,
            "abort":    OrchestratorState.CLOSED_ABORTED,
        }
        if user_decision not in final_state_map:
            raise ValueError(f"Décision inconnue : {user_decision}")

        self._transition(final_state_map[user_decision], payload={
            "user_decision": user_decision,
        })

    # ── Agrégation et convergence (Modèle V2, §9) ───────────────────────────

    def _check_aggregation_ready(self) -> None:
        """
        Vérifie si tous les sous-processus sont terminaux.
        Si oui, déclenche l'Aggregation puis la User Validation.

        Condition (Modèle V2, §9) :
            Tous les acteurs activés sont COMPLETED, ESCALATED, ou SKIPPED.
        """
        if self._state != OrchestratorState.ORCHESTRATING:
            return

        all_terminal = all(p.is_terminal for p in self._actors.values())
        if not all_terminal:
            return

        # Calcul du résultat agrégé
        results       = {a.value: p.state.value for a, p in self._actors.items()}
        any_escalated = any(
            p.state == ActorState.ESCALATED
            for p in self._actors.values()
            if p.state != ActorState.SKIPPED
        )

        self._transition(OrchestratorState.AGGREGATION, payload={
            "actor_results": results,
            "any_escalated": any_escalated,
        })

        # USER_VALIDATION toujours requis (Modèle V2, §9)
        self._transition(OrchestratorState.USER_VALIDATION, payload={
            "recommendation": "CLOSED_ESCALATED" if any_escalated else "CLOSED_SUCCESS",
            "summary":        self._build_summary(),
        })

    def _build_summary(self) -> dict:
        """Construit un résumé du cas pour la validation utilisateur."""
        return {
            "case_id":        self.case_id,
            "total_events":   self.log.current_version,
            "actor_states":   {a.value: p.state.value for a, p in self._actors.items()},
            "use_case":       self._case_context.get("use_case", "unknown"),
        }

    # ── Helpers internes ─────────────────────────────────────────────────────

    def _transition(self, new_state: OrchestratorState, payload: dict) -> None:
        old_state    = self._state
        self._state  = new_state
        self.log.append(
            actor      = "ORCHESTRATOR",
            event_type = "STATE_TRANSITION",
            payload    = {
                "from": old_state.value,
                "to":   new_state.value,
                **payload,
            },
        )

    def _assert_state(self, expected: OrchestratorState) -> None:
        if self._state != expected:
            raise ValueError(
                f"[ORCHESTRATOR] Transition invalide : "
                f"état attendu={expected.value}, état actuel={self._state.value}"
            )

    def status(self) -> str:
        """Affichage lisible de l'état complet du cas."""
        lines = [
            f"{'='*60}",
            f"HelveVista Case — {self.case_id}",
            f"Orchestrator State : {self._state.value}",
            f"{'─'*60}",
        ]
        for actor, process in self._actors.items():
            lines.append(f"  {actor.value:<12} → {process.state.value}")
        lines.append(f"{'─'*60}")
        lines.append(f"Event Log : {self.log.current_version} événements")
        lines.append(f"{'='*60}")
        return "\n".join(lines)

"""
core/states.py
--------------
Définition de tous les états du modèle HelveVista V2.

RÈGLE FONDAMENTALE (Modèle V2, §11) :
    Ce fichier appartient à la couche de CONTRÔLE déterministe.
    Aucune logique LLM ici. Aucun appel API ici.
"""

from enum import Enum


# ── États de l'orchestration principale ─────────────────────────────────────

class OrchestratorState(Enum):
    """État global du cas HelveVista (orchestrateur principal)."""
    INIT              = "INIT"
    STRUCTURED        = "STRUCTURED"
    CONDITIONAL_FORK  = "CONDITIONAL_FORK"
    ORCHESTRATING     = "ORCHESTRATING"   # sous-processus actifs en parallèle
    AGGREGATION       = "AGGREGATION"
    USER_VALIDATION   = "USER_VALIDATION"
    CLOSED_SUCCESS    = "CLOSED_SUCCESS"
    CLOSED_ESCALATED  = "CLOSED_ESCALATED"
    CLOSED_ABORTED    = "CLOSED_ABORTED"


# ── États d'un sous-processus institutionnel ────────────────────────────────

class ActorState(Enum):
    """
    État d'une mini-state-machine par acteur institutionnel.
    (Modèle V2, §4 : REQUEST_SENT → WAITING → RESPONSE_RECEIVED | TIMEOUT | CONFLICT)
    """
    PENDING            = "PENDING"           # acteur activé mais pas encore démarré
    REQUEST_SENT       = "REQUEST_SENT"      # requête envoyée à l'institution
    WAITING            = "WAITING"           # en attente de réponse
    RESPONSE_RECEIVED  = "RESPONSE_RECEIVED" # réponse valide reçue
    TIMEOUT            = "TIMEOUT"           # délai dépassé, retry en cours
    CONFLICT_DETECTED  = "CONFLICT_DETECTED" # incohérence de version détectée
    HITL_REQUIRED      = "HITL_REQUIRED"     # intervention humaine requise
    ESCALATED          = "ESCALATED"         # escalade après retries épuisés
    COMPLETED          = "COMPLETED"         # sous-processus terminé avec succès
    SKIPPED            = "SKIPPED"           # acteur non activé (conditionnel)


# ── Acteurs institutionnels ──────────────────────────────────────────────────

class Actor(Enum):
    """
    Acteurs institutionnels du use case Stellenwechsel.
    (Modèle V2, §3.1 : alte PK, neue PK, AVS optionelle)
    """
    OLD_PK = "OLD_PK"   # Alte Pensionskasse — critique
    NEW_PK = "NEW_PK"   # Neue Pensionskasse — critique
    AVS    = "AVS"      # AHV-Ausgleichskasse — optionelle, non-critique


# ── Terminaison d'un acteur ──────────────────────────────────────────────────

TERMINAL_ACTOR_STATES = {
    ActorState.COMPLETED,
    ActorState.ESCALATED,
    ActorState.SKIPPED,
}

SUCCESSFUL_ACTOR_STATES = {
    ActorState.COMPLETED,
    ActorState.SKIPPED,
}

"""
tests/test_stellenwechsel.py
-----------------------------
Test du scénario complet Stellenwechsel — sans LLM.

Valide :
    H1 — Safety : Versionsprüfung détecte les données obsolètes
    H2 — Liveness : Timeout + Escalation évitent les deadlocks

Exécution :
    python -m pytest tests/test_stellenwechsel.py -v
    ou directement :
    python tests/test_stellenwechsel.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.states import Actor, ActorState, OrchestratorState
from core.orchestrator import HelveVistaOrchestrator


# ── Couleurs terminal ─────────────────────────────────────────────────────────

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

def ok(msg):  print(f"{GREEN}  ✓ {msg}{RESET}")
def fail(msg): print(f"{RED}  ✗ {msg}{RESET}"); sys.exit(1)
def info(msg): print(f"{BLUE}  → {msg}{RESET}")
def title(msg): print(f"\n{BOLD}{YELLOW}{'─'*55}{RESET}\n{BOLD}  {msg}{RESET}\n{'─'*55}")


# ════════════════════════════════════════════════════════════
# SCÉNARIO 1 — Chemin heureux (Happy Path)
# Tous les acteurs répondent dans les délais, sans conflit
# ════════════════════════════════════════════════════════════

def test_happy_path():
    title("SCÉNARIO 1 — Happy Path (Stellenwechsel standard)")

    orch = HelveVistaOrchestrator(case_id="TEST-HAPPY-001")

    # ── INIT → STRUCTURED ────────────────────────────────────────────────────
    info("structure_case()")
    orch.structure_case(
        raw_input = "Ich wechsle meinen Job am 1. April. Was muss ich für meine Pensionskasse tun?",
        structured_context = {
            "use_case": "STELLENWECHSEL",
            "actors_involved": ["OLD_PK", "NEW_PK"],
            "avs_required": False,
            "user_summary": "Stellenwechsel per 1. April — alte und neue PK involviert.",
        }
    )
    assert orch.state == OrchestratorState.STRUCTURED
    ok(f"État orchestrateur : {orch.state.value}")

    # ── CONDITIONAL FORK — OLD_PK + NEW_PK, pas de AVS ───────────────────────
    info("execute_conditional_fork({OLD_PK, NEW_PK})")
    orch.execute_conditional_fork(activated_actors={Actor.OLD_PK, Actor.NEW_PK})
    assert orch.state == OrchestratorState.ORCHESTRATING
    assert orch.actors[Actor.AVS].state == ActorState.SKIPPED
    ok(f"AVS correctement skippé : {orch.actors[Actor.AVS].state.value}")
    ok(f"État orchestrateur : {orch.state.value}")

    # ── Envoi des requêtes ────────────────────────────────────────────────────
    info("send_actor_request(OLD_PK)")
    orch.send_actor_request(Actor.OLD_PK, {"document": "Freizügigkeitsabrechnung anfordern"})
    assert orch.actors[Actor.OLD_PK].state == ActorState.WAITING
    ok(f"OLD_PK : {orch.actors[Actor.OLD_PK].state.value}")

    info("send_actor_request(NEW_PK)")
    orch.send_actor_request(Actor.NEW_PK, {"document": "Eintrittsformular anfordern"})
    assert orch.actors[Actor.NEW_PK].state == ActorState.WAITING
    ok(f"NEW_PK : {orch.actors[Actor.NEW_PK].state.value}")

    # ── Réponses valides (version courante = 5 à ce stade) ────────────────────
    current_v = orch.log.current_version
    info(f"receive_actor_response(OLD_PK, version={current_v})")
    orch.receive_actor_response(
        Actor.OLD_PK,
        response = {"freizuegigkeit_chf": 45200, "austritt": "2025-03-31"},
        response_version = current_v   # version valide → pas de conflit
    )
    assert orch.actors[Actor.OLD_PK].state == ActorState.COMPLETED
    ok(f"OLD_PK : {orch.actors[Actor.OLD_PK].state.value}")

    current_v = orch.log.current_version
    info(f"receive_actor_response(NEW_PK, version={current_v})")
    orch.receive_actor_response(
        Actor.NEW_PK,
        response = {"eintritt": "2025-04-01", "bvg_koordinationsabzug": 26460},
        response_version = current_v
    )
    assert orch.actors[Actor.NEW_PK].state == ActorState.COMPLETED
    ok(f"NEW_PK : {orch.actors[Actor.NEW_PK].state.value}")

    # ── Agrégation automatique ────────────────────────────────────────────────
    assert orch.state == OrchestratorState.USER_VALIDATION
    ok(f"Agrégation déclenchée → {orch.state.value}")

    # ── Validation utilisateur ────────────────────────────────────────────────
    info("validate_and_close('accept')")
    orch.validate_and_close("accept")
    assert orch.state == OrchestratorState.CLOSED_SUCCESS
    ok(f"État final : {orch.state.value}")

    print(f"\n{orch.status()}")
    print(f"\n{GREEN}{BOLD}SCÉNARIO 1 PASSED ✓{RESET}\n")


# ════════════════════════════════════════════════════════════
# SCÉNARIO 2 — H1 Safety : Versionsprüfung
# Une réponse avec une version obsolète doit déclencher CONFLICT_DETECTED
# ════════════════════════════════════════════════════════════

def test_version_conflict():
    title("SCÉNARIO 2 — H1 Safety : Versionsprüfung (données obsolètes)")

    orch = HelveVistaOrchestrator(case_id="TEST-CONFLICT-001")

    orch.structure_case(
        raw_input = "Stellenwechsel mit IK-Auszug",
        structured_context = {
            "use_case": "STELLENWECHSEL",
            "actors_involved": ["OLD_PK", "NEW_PK", "AVS"],
            "avs_required": True,
            "user_summary": "Stellenwechsel mit AHV-Kontoauszug.",
        }
    )
    orch.execute_conditional_fork(activated_actors={Actor.OLD_PK, Actor.NEW_PK, Actor.AVS})

    # Envoi des requêtes
    orch.send_actor_request(Actor.OLD_PK, {"doc": "Freizügigkeit"})
    orch.send_actor_request(Actor.NEW_PK, {"doc": "Eintritt"})
    orch.send_actor_request(Actor.AVS,    {"doc": "IK-Auszug"})

    # OLD_PK répond avec version courante → OK
    v_current = orch.log.current_version
    info(f"OLD_PK répond avec version valide ({v_current})")
    orch.receive_actor_response(Actor.OLD_PK, {"data": "ok"}, response_version=v_current)
    assert orch.actors[Actor.OLD_PK].state == ActorState.COMPLETED
    ok(f"OLD_PK COMPLETED (version valide)")

    # NEW_PK répond avec une version OBSOLÈTE (avant les derniers événements)
    v_obsolete = 1  # bien inférieur à la version courante
    info(f"NEW_PK répond avec version OBSOLÈTE ({v_obsolete} < {orch.log.current_version})")
    orch.receive_actor_response(Actor.NEW_PK, {"data": "stale"}, response_version=v_obsolete)

    # H1 : le système doit détecter le conflit et passer en HITL_REQUIRED
    assert orch.actors[Actor.NEW_PK].state == ActorState.HITL_REQUIRED, \
        f"Attendu HITL_REQUIRED, obtenu {orch.actors[Actor.NEW_PK].state.value}"
    ok(f"NEW_PK : CONFLICT_DETECTED → HITL_REQUIRED ✓ (Safety validée)")

    # Résolution par l'utilisateur
    info("Résolution HITL par l'utilisateur")
    orch.resolve_hitl(Actor.NEW_PK, resolution={"action": "accept_new_data", "confirmed_by": "user"})
    assert orch.actors[Actor.NEW_PK].state == ActorState.COMPLETED
    ok("NEW_PK résolu → COMPLETED")

    # AVS répond correctement
    orch.receive_actor_response(Actor.AVS, {"ik_auszug": "disponible"}, response_version=orch.log.current_version)

    assert orch.state == OrchestratorState.USER_VALIDATION
    orch.validate_and_close("accept")
    assert orch.state == OrchestratorState.CLOSED_SUCCESS

    print(f"\n{orch.status()}")
    print(f"\n{GREEN}{BOLD}SCÉNARIO 2 PASSED ✓ — H1 Safety validée{RESET}\n")


# ════════════════════════════════════════════════════════════
# SCÉNARIO 3 — H2 Liveness : Timeout + Escalation
# Un acteur ne répond jamais → Timeout → Escalation (pas de deadlock)
# ════════════════════════════════════════════════════════════

def test_timeout_escalation():
    title("SCÉNARIO 3 — H2 Liveness : Timeout & Escalation (pas de deadlock)")
    info("Note : timeout simulé à 0.1s pour le test")

    from core.actor_process import ActorConfig, DEFAULT_CONFIGS
    import copy

    orch = HelveVistaOrchestrator(case_id="TEST-TIMEOUT-001")

    # Override du timeout à 0.1s pour le test
    fast_configs = copy.deepcopy(DEFAULT_CONFIGS)
    fast_configs[Actor.OLD_PK] = ActorConfig(
        actor=Actor.OLD_PK, is_optional=False,
        timeout_seconds=0.1, max_retries=1
    )

    orch.structure_case(
        raw_input = "Stellenwechsel — alte PK antwortet nicht",
        structured_context = {
            "use_case": "STELLENWECHSEL",
            "actors_involved": ["OLD_PK", "NEW_PK"],
            "avs_required": False,
            "user_summary": "Alter Arbeitgeber reagiert nicht auf Anfragen.",
        }
    )
    orch.execute_conditional_fork(activated_actors={Actor.OLD_PK, Actor.NEW_PK})

    # Override manual du config pour le timeout rapide
    orch._actors[Actor.OLD_PK].config = fast_configs[Actor.OLD_PK]

    orch.send_actor_request(Actor.OLD_PK, {"doc": "Freizügigkeit"})
    orch.send_actor_request(Actor.NEW_PK, {"doc": "Eintritt"})

    # Attendre que le timeout se produise
    import time
    info("Simulation d'une non-réponse de OLD_PK (attente 0.25s)...")
    time.sleep(0.25)

    # tick() déclenche la vérification des timeouts
    orch.tick()
    info(f"Après tick() : OLD_PK = {orch.actors[Actor.OLD_PK].state.value}")

    # Selon les retries (max_retries=1), OLD_PK sera en WAITING (retry) ou ESCALATED
    # On simule un 2ème timeout
    time.sleep(0.25)
    orch.tick()

    assert orch.actors[Actor.OLD_PK].state == ActorState.ESCALATED, \
        f"Attendu ESCALATED, obtenu {orch.actors[Actor.OLD_PK].state.value}"
    ok(f"OLD_PK ESCALATED après {fast_configs[Actor.OLD_PK].max_retries} retry(s) ✓")
    ok("H2 Liveness validée : pas de deadlock")

    # NEW_PK répond normalement
    orch.receive_actor_response(Actor.NEW_PK, {"data": "ok"}, response_version=orch.log.current_version)
    assert orch.actors[Actor.NEW_PK].state == ActorState.COMPLETED

    # Agrégation avec escalade → recommandation CLOSED_ESCALATED
    assert orch.state == OrchestratorState.USER_VALIDATION
    info("Validation utilisateur avec escalade")
    orch.validate_and_close("escalate")
    assert orch.state == OrchestratorState.CLOSED_ESCALATED
    ok(f"État final : {orch.state.value} ✓")

    print(f"\n{orch.status()}")
    print(orch.log.summary())
    print(f"\n{GREEN}{BOLD}SCÉNARIO 3 PASSED ✓ — H2 Liveness validée{RESET}\n")


# ════════════════════════════════════════════════════════════
# RUNNER
# ════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print(f"\n{BOLD}HelveVista — Tests de validation du modèle V2{RESET}")
    print(f"Hypothèses testées : H1 (Safety) et H2 (Liveness)\n")

    test_happy_path()
    test_version_conflict()
    test_timeout_escalation()

    print(f"\n{'='*55}")
    print(f"{GREEN}{BOLD}  TOUS LES SCÉNARIOS PASSÉS ✓{RESET}")
    print(f"  H1 (Safety)   — Versionsprüfung opérationnelle")
    print(f"  H2 (Liveness) — Timeout & Escalation sans deadlock")
    print(f"{'='*55}\n")

"""
main.py
-------
Point d'entrée interactif de HelveVista.
Démontre le scénario Stellenwechsel end-to-end.

Usage :
    python main.py                    # démo simulée (sans API key)
    ANTHROPIC_API_KEY=sk-... python main.py   # avec LLM réel
"""

import os
import sys

# Ajout du path pour les imports relatifs
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.states import Actor, OrchestratorState
from core.orchestrator import HelveVistaOrchestrator

BOLD   = "\033[1m"
BLUE   = "\033[94m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RESET  = "\033[0m"


def run_demo():
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  HelveVista — Démonstration Prototype V2{RESET}")
    print(f"{BOLD}  Use Case : Stellenwechsel{RESET}")
    print(f"{BOLD}{'='*60}{RESET}\n")

    USE_LLM = bool(os.environ.get("ANTHROPIC_API_KEY"))

    if USE_LLM:
        print(f"{GREEN}LLM activé — Anthropic Claude API{RESET}\n")
        from llm.structurer import structure_user_input, generate_case_summary
    else:
        print(f"{YELLOW}Mode démo — LLM simulé (définir ANTHROPIC_API_KEY pour activer){RESET}\n")

    # ── 1. Saisie utilisateur ────────────────────────────────────────────────
    raw_input = (
        "Ich wechsle meinen Job per 1. April 2025. "
        "Mein aktueller Arbeitgeber ist die Firma Müller AG in Zürich, "
        "der neue ist die Novartis Basel. "
        "Was muss ich bezüglich meiner Pensionskasse und AHV unternehmen?"
    )
    print(f"{BLUE}Nutzereingabe :{RESET}")
    print(f"  «{raw_input}»\n")

    # ── 2. Structuration ─────────────────────────────────────────────────────
    if USE_LLM:
        print(f"{BLUE}LLM strukturiert den Fall...{RESET}")
        context = structure_user_input(raw_input)
    else:
        # Contexte simulé pour la démo
        context = {
            "use_case":        "STELLENWECHSEL",
            "actors_involved": ["OLD_PK", "NEW_PK", "AVS"],
            "avs_required":    True,
            "user_summary":    (
                "Der Nutzer wechselt seinen Arbeitsplatz per 1. April 2025 "
                "von der Müller AG Zürich zur Novartis Basel. "
                "Es sind die alte Pensionskasse, die neue Pensionskasse "
                "und die AHV-Ausgleichskasse involviert."
            ),
            "missing_info":    [],
            "actors_enum":     [Actor.OLD_PK, Actor.NEW_PK, Actor.AVS],
        }

    print(f"  Use Case    : {context['use_case']}")
    print(f"  Akteure     : {context['actors_involved']}")
    print(f"  AVS nötig   : {context.get('avs_required', False)}")
    print(f"  Zusammenfassung : {context['user_summary'][:80]}...\n")

    # ── 3. Orchestration ─────────────────────────────────────────────────────
    orch = HelveVistaOrchestrator()

    orch.structure_case(raw_input=raw_input, structured_context=context)
    print(f"{GREEN}✓ STRUCTURED{RESET}")

    activated = set(context.get("actors_enum", [Actor.OLD_PK, Actor.NEW_PK]))
    orch.execute_conditional_fork(activated_actors=activated)
    print(f"{GREEN}✓ CONDITIONAL FORK → {[a.value for a in activated]}{RESET}")

    # ── 4. Requêtes aux acteurs ───────────────────────────────────────────────
    for actor in activated:
        orch.send_actor_request(actor, {"type": "initial_request", "use_case": context["use_case"]})
        print(f"  → Anfrage gesendet an {actor.value}")

    print()

    # ── 5. Simulation des réponses ────────────────────────────────────────────
    print(f"{BLUE}Simulation institutioneller Antworten...{RESET}")

    for actor in activated:
        v = orch.log.current_version
        responses = {
            Actor.OLD_PK: {"freizuegigkeit_chf": 45200, "status": "Austritt bestätigt"},
            Actor.NEW_PK: {"eintritt": "2025-04-01", "bvg_pflicht": True},
            Actor.AVS:    {"ik_auszug": "verfügbar", "beitragsjahre": 12},
        }
        orch.receive_actor_response(actor, responses[actor], response_version=v)
        state = orch.actors[actor].state
        color = GREEN if state.value == "COMPLETED" else YELLOW
        print(f"  {color}← {actor.value} : {state.value}{RESET}")

    print()

    # ── 6. Résultat final ─────────────────────────────────────────────────────
    print(orch.status())

    if orch.state == OrchestratorState.USER_VALIDATION:
        print(f"\n{BOLD}Empfehlung an den Nutzer :{RESET}")

        if USE_LLM:
            summary_text = generate_case_summary(orch._build_summary())
            print(f"  {summary_text}")
        else:
            print(
                "  Ihr Stellenwechsel-Prozess konnte erfolgreich koordiniert werden. "
                "Alle relevanten Institutionen haben geantwortet. "
                "Bitte überprüfen Sie die Zusammenfassung und bestätigen Sie."
            )

        print(f"\n{BLUE}Nutzerentscheid: 'accept'{RESET}")
        orch.validate_and_close("accept")

    print(f"\n{BOLD}{GREEN}Finaler Status : {orch.state.value}{RESET}")
    print(f"Event Log     : {orch.log.current_version} Ereignisse protokolliert")
    print(f"\n{orch.log.summary()}\n")


if __name__ == "__main__":
    run_demo()

"""
main.py
-------
Interaktive CLI für HelveVista.

Führt den Nutzer Schritt für Schritt durch den Stellenwechsel-Prozess:
  1. Situationsbeschreibung eingeben
  2. Akteure aktivieren (OLD_PK, NEW_PK, AVS)
  3. Orchestrierung live verfolgen
  4. Ergebnis bestätigen oder eskalieren

Verwendung:
    python prototype/main.py
    ANTHROPIC_API_KEY=sk-... python prototype/main.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.states import Actor, ActorState, OrchestratorState
from core.orchestrator import HelveVistaOrchestrator

# ── Farben ────────────────────────────────────────────────────────────────────

BOLD   = "\033[1m"
DIM    = "\033[2m"
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
CYAN   = "\033[96m"
RESET  = "\033[0m"

# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def header(text: str) -> None:
    width = 62
    print(f"\n{BOLD}{CYAN}{'─' * width}{RESET}")
    print(f"{BOLD}{CYAN}  {text}{RESET}")
    print(f"{BOLD}{CYAN}{'─' * width}{RESET}")


def step(n: int, text: str) -> None:
    print(f"\n{BOLD}[Schritt {n}]{RESET} {text}")


def ok(text: str) -> None:
    print(f"  {GREEN}✓{RESET}  {text}")


def info(text: str) -> None:
    print(f"  {BLUE}→{RESET}  {text}")


def warn(text: str) -> None:
    print(f"  {YELLOW}!{RESET}  {text}")


def err(text: str) -> None:
    print(f"  {RED}✗{RESET}  {text}")


def ask(prompt: str, default: str = "") -> str:
    hint = f" {DIM}[{default}]{RESET}" if default else ""
    try:
        answer = input(f"\n{BOLD}{prompt}{hint}{RESET}\n> ").strip()
    except (KeyboardInterrupt, EOFError):
        print(f"\n\n{YELLOW}Abgebrochen.{RESET}\n")
        sys.exit(0)
    return answer if answer else default


def actor_state_badge(state: ActorState) -> str:
    badges = {
        ActorState.COMPLETED:     f"{GREEN}COMPLETED ✓{RESET}",
        ActorState.WAITING:       f"{YELLOW}WAITING…{RESET}",
        ActorState.ESCALATED:     f"{RED}ESKALIERT ✗{RESET}",
        ActorState.HITL_REQUIRED: f"{RED}KONFLIKT — Eingriff nötig{RESET}",
        ActorState.SKIPPED:       f"{DIM}ÜBERSPRUNGEN{RESET}",
        ActorState.TIMEOUT:       f"{YELLOW}TIMEOUT{RESET}",
    }
    return badges.get(state, state.value)


# ── Aktor-Auswahl ─────────────────────────────────────────────────────────────

ACTOR_INFO = {
    Actor.OLD_PK: ("OLD_PK", "Alte Pensionskasse",   "Freizügigkeitsabrechnung, Austrittsbestätigung"),
    Actor.NEW_PK: ("NEW_PK", "Neue Pensionskasse",   "Eintrittsanmeldung, BVG-Pflicht"),
    Actor.AVS:    ("AVS",    "AHV-Ausgleichskasse",  "IK-Auszug, Beitragsjahre (optional)"),
}

SIMULATED_RESPONSES = {
    Actor.OLD_PK: {"freizuegigkeit_chf": 45_200, "austritt": "2025-03-31", "status": "Austritt bestätigt"},
    Actor.NEW_PK: {"eintritt": "2025-04-01", "bvg_koordinationsabzug": 26_460, "bvg_pflicht": True},
    Actor.AVS:    {"ik_auszug": "verfügbar", "beitragsjahre": 12, "luecken": 0},
}


def select_actors(suggested: list[Actor]) -> set[Actor]:
    """Zeigt die drei Akteure und lässt den Nutzer auswählen."""
    print()
    for i, actor in enumerate(Actor, 1):
        code, name, desc = ACTOR_INFO[actor]
        suggested_mark = f" {GREEN}← vorgeschlagen{RESET}" if actor in suggested else ""
        print(f"  {BOLD}[{i}] {code}{RESET}  —  {name}{suggested_mark}")
        print(f"       {DIM}{desc}{RESET}")

    suggested_codes = ", ".join(a.value for a in suggested) if suggested else "1, 2"
    raw = ask(
        "Akteure aktivieren? Nummer(n) eingeben, z.B. '1 2' oder '1 2 3'",
        default=", ".join(str(i) for i, a in enumerate(Actor, 1) if a in suggested),
    )

    # Nummern oder Codes parsen
    chosen: set[Actor] = set()
    all_actors = list(Actor)
    for token in raw.replace(",", " ").split():
        if token.isdigit():
            idx = int(token) - 1
            if 0 <= idx < len(all_actors):
                chosen.add(all_actors[idx])
        else:
            for a in Actor:
                if a.value == token.upper():
                    chosen.add(a)

    if not chosen:
        warn("Keine gültige Auswahl — OLD_PK und NEW_PK werden aktiviert.")
        chosen = {Actor.OLD_PK, Actor.NEW_PK}

    return chosen


# ── Orchestrierungsschritte ───────────────────────────────────────────────────

def run_requests(orch: HelveVistaOrchestrator, activated: set[Actor], use_case: str) -> None:
    """Sendet Anfragen an alle aktivierten Akteure."""
    for actor in Actor:
        if actor not in activated:
            continue
        _, name, _ = ACTOR_INFO[actor]
        orch.send_actor_request(actor, {"type": "initial_request", "use_case": use_case})
        info(f"Anfrage gesendet an {BOLD}{name}{RESET}  [{YELLOW}WAITING…{RESET}]")
        time.sleep(0.3)


def run_responses(orch: HelveVistaOrchestrator, activated: set[Actor]) -> None:
    """Simuliert institutionelle Antworten, eine nach der anderen."""
    for actor in Actor:
        if actor not in activated:
            continue
        _, name, _ = ACTOR_INFO[actor]
        print(f"  {DIM}← {name} antwortet…{RESET}", end="", flush=True)
        time.sleep(0.6)

        v = orch.log.current_version
        orch.receive_actor_response(actor, SIMULATED_RESPONSES[actor], response_version=v)
        state = orch.actors[actor].state
        print(f"\r  {BOLD}← {name:<28}{RESET}  {actor_state_badge(state)}")


# ── Entscheid ─────────────────────────────────────────────────────────────────

def user_decision(orch: HelveVistaOrchestrator) -> None:
    """Zeigt die Empfehlung und fragt nach dem Nutzerentscheid."""
    actors = orch.actors
    any_escalated = any(
        p.state == ActorState.ESCALATED
        for a, p in actors.items()
        if p.state != ActorState.SKIPPED
    )
    recommendation = "escalate" if any_escalated else "accept"

    print()
    if any_escalated:
        warn(f"Empfehlung: {BOLD}ESKALIEREN{RESET} — ein oder mehrere Akteure haben nicht geantwortet.")
    else:
        ok(f"Alle Akteure haben geantwortet. Empfehlung: {BOLD}ABSCHLIESSEN{RESET}")

    decision = ask(
        "Entscheid: 'accept' (Abschliessen), 'escalate' (Eskalieren), 'abort' (Abbrechen)",
        default=recommendation,
    )
    if decision not in ("accept", "escalate", "abort"):
        warn(f"Unbekannte Eingabe '{decision}' — verwende '{recommendation}'.")
        decision = recommendation

    orch.validate_and_close(decision)


# ── Hauptprogramm ─────────────────────────────────────────────────────────────

def main() -> None:
    USE_LLM = bool(os.environ.get("ANTHROPIC_API_KEY"))

    # ── Titel ────────────────────────────────────────────────────────────────
    print(f"\n{BOLD}{'=' * 62}{RESET}")
    print(f"{BOLD}  HelveVista — Orchestrierungssystem Schweizer Vorsorge{RESET}")
    print(f"{BOLD}  Use Case: Stellenwechsel{RESET}")
    print(f"{BOLD}{'=' * 62}{RESET}")

    if USE_LLM:
        print(f"\n  {GREEN}LLM aktiv — Anthropic Claude API{RESET}")
        from llm.structurer import structure_user_input, generate_case_summary
    else:
        print(f"\n  {YELLOW}Demo-Modus — ANTHROPIC_API_KEY nicht gesetzt{RESET}")
        print(f"  {DIM}(Akteurvorschläge werden manuell bestätigt){RESET}")

    # ── Schritt 1: Situationsbeschreibung ─────────────────────────────────
    header("Schritt 1 — Ihre Situation")
    print(f"  Beschreiben Sie Ihre Situation auf Deutsch.")
    print(f"  {DIM}Beispiel: «Ich wechsle meinen Job per 1. April 2025 von der Müller AG zur Novartis.»{RESET}")

    raw = ask("Ihre Eingabe")
    if not raw:
        raw = (
            "Ich wechsle meinen Job per 1. April 2025 von der Müller AG Zürich "
            "zur Novartis Basel. Was muss ich für meine Pensionskasse und AHV tun?"
        )
        info(f"Beispiel verwendet: «{raw[:70]}…»")

    # ── Schritt 2: Fall strukturieren ─────────────────────────────────────
    header("Schritt 2 — Fall strukturieren")

    suggested_actors: list[Actor] = [Actor.OLD_PK, Actor.NEW_PK]

    if USE_LLM:
        info("LLM analysiert Ihre Eingabe…")
        context = structure_user_input(raw)
        suggested_actors = context.get("actors_enum", [Actor.OLD_PK, Actor.NEW_PK])
        ok(f"Use Case erkannt: {BOLD}{context['use_case']}{RESET}")
        ok(f"Vorgeschlagene Akteure: {[a.value for a in suggested_actors]}")
        print(f"\n  {DIM}{context['user_summary']}{RESET}")
    else:
        context = {
            "use_case":        "STELLENWECHSEL",
            "actors_involved": ["OLD_PK", "NEW_PK"],
            "avs_required":    False,
            "user_summary":    raw,
            "missing_info":    [],
            "actors_enum":     [Actor.OLD_PK, Actor.NEW_PK],
        }
        ok(f"Use Case: {BOLD}STELLENWECHSEL{RESET}")
        info("AVS wird nur bei IK-Auszug-Bedarf aktiviert — bitte selbst auswählen.")

    # ── Schritt 3: Akteure auswählen ──────────────────────────────────────
    header("Schritt 3 — Akteure aktivieren")
    activated = select_actors(suggested_actors)

    print()
    for actor in Actor:
        _, name, _ = ACTOR_INFO[actor]
        if actor in activated:
            ok(f"{BOLD}{name}{RESET} aktiviert")
        else:
            info(f"{DIM}{name} übersprungen{RESET}")

    # ── Schritt 4: Orchestrierung starten ─────────────────────────────────
    header("Schritt 4 — Orchestrierung")

    orch = HelveVistaOrchestrator()

    context["actors_enum"] = list(activated)
    context["actors_involved"] = [a.value for a in activated]
    orch.structure_case(raw_input=raw, structured_context=context)
    ok(f"Status: {BOLD}{orch.state.value}{RESET}")

    orch.execute_conditional_fork(activated_actors=activated)
    ok(f"Status: {BOLD}{orch.state.value}{RESET}  →  {len(activated)} Akteur(e) aktiv")

    print()
    step(4, "Anfragen senden…")
    run_requests(orch, activated, context["use_case"])

    print()
    step(5, "Auf Antworten warten…")
    run_responses(orch, activated)

    # ── Schritt 5: Ergebnis ───────────────────────────────────────────────
    header("Schritt 5 — Ergebnis")
    print(f"\n{orch.status()}\n")

    if USE_LLM and orch.state == OrchestratorState.USER_VALIDATION:
        info("LLM formuliert Zusammenfassung…")
        summary_text = generate_case_summary(orch._build_summary())
        print(f"\n  {summary_text}\n")

    # ── Schritt 6: Nutzerentscheid ────────────────────────────────────────
    header("Schritt 6 — Ihr Entscheid")
    user_decision(orch)

    # ── Abschluss ─────────────────────────────────────────────────────────
    final_colors = {
        OrchestratorState.CLOSED_SUCCESS:   GREEN,
        OrchestratorState.CLOSED_ESCALATED: YELLOW,
        OrchestratorState.CLOSED_ABORTED:   RED,
    }
    color = final_colors.get(orch.state, RESET)

    print(f"\n{BOLD}{'=' * 62}{RESET}")
    print(f"  Finaler Status : {color}{BOLD}{orch.state.value}{RESET}")
    print(f"  Ereignisse     : {orch.log.current_version} im Event Log protokolliert")
    print(f"{BOLD}{'=' * 62}{RESET}\n")


if __name__ == "__main__":
    main()

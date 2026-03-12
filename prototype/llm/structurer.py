"""
llm/structurer.py
-----------------
Couche LLM de HelveVista — séparée strictement de la Kontrolllogik.

RÔLE AUTORISÉ (Modèle V2, §11) :
    ✅ Structurer la saisie utilisateur
    ✅ Extraire les informations pertinentes
    ✅ Formuler les outputs pour l'utilisateur
    ✅ Expliquer les états du système en langage naturel

RÔLE INTERDIT (Modèle V2, §11) :
    ❌ Changer un état de la state machine
    ❌ Influencer la logique de transition
    ❌ Prendre des décisions finales

PROVIDER : Anthropic Claude API
"""

import os
import json
import anthropic
from typing import Optional

from ..core.states import Actor


# ── Client Anthropic ─────────────────────────────────────────────────────────

def _get_client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "Variable d'environnement ANTHROPIC_API_KEY manquante. "
            "Définis-la avant de lancer HelveVista."
        )
    return anthropic.Anthropic(api_key=api_key)


# ── Structuration du cas (INIT → STRUCTURED) ─────────────────────────────────

STRUCTURE_SYSTEM_PROMPT = """Tu es un assistant spécialisé dans le système de prévoyance suisse (3 piliers).
Tu analyses la situation d'un utilisateur et tu extrais les informations structurées.

Tu dois répondre UNIQUEMENT avec un objet JSON valide, sans texte avant ou après.

Format attendu :
{
  "use_case": "STELLENWECHSEL" | "BVG_EINKAUF" | "AUTRE",
  "actors_involved": ["OLD_PK", "NEW_PK", "AVS"],
  "avs_required": true | false,
  "user_summary": "Résumé en allemand de la situation de l'utilisateur (2-3 phrases)",
  "missing_info": ["liste des informations manquantes si applicable"]
}

Règles :
- actors_involved doit contenir uniquement les acteurs réellement mentionnés ou impliqués
- Pour un Stellenwechsel standard : OLD_PK et NEW_PK sont toujours impliqués
- AVS est optionnel — uniquement si l'utilisateur mentionne l'IK-Auszug ou des questions AHV
- user_summary doit être en allemand, formulé pour l'utilisateur final
"""


def structure_user_input(raw_input: str) -> dict:
    """
    Analyse la saisie utilisateur et retourne un contexte structuré.
    
    Appelé par l'orchestrateur dans structure_case().
    Le résultat ne pilote PAS les transitions — il informe uniquement.
    
    Returns:
        dict avec clés: use_case, actors_involved, avs_required, user_summary, missing_info
    """
    client = _get_client()

    message = client.messages.create(
        model      = "claude-sonnet-4-20250514",
        max_tokens = 512,
        system     = STRUCTURE_SYSTEM_PROMPT,
        messages   = [
            {"role": "user", "content": raw_input}
        ]
    )

    raw = message.content[0].text.strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # Fallback sécurisé — ne bloque jamais la logique de contrôle
        result = {
            "use_case":        "AUTRE",
            "actors_involved": ["OLD_PK", "NEW_PK"],
            "avs_required":    False,
            "user_summary":    raw_input[:200],
            "missing_info":    ["Strukturierung fehlgeschlagen — manuelle Überprüfung erforderlich"],
        }

    # Conversion des strings en enum Actor (pour le conditional fork)
    actor_map = {a.value: a for a in Actor}
    result["actors_enum"] = [
        actor_map[a] for a in result.get("actors_involved", [])
        if a in actor_map
    ]

    return result


# ── Formulation d'une requête institutionnelle ───────────────────────────────

REQUEST_SYSTEM_PROMPT = """Tu es un assistant administratif suisse.
Tu rédiges des demandes formelles et claires à des institutions de prévoyance (Pensionskasse, AHV).
Réponds UNIQUEMENT avec le texte de la demande, en allemand, sans salutation ni signature.
Sois précis, formel, et concis (max. 5 phrases).
"""


def formulate_request(actor_name: str, case_context: dict) -> str:
    """
    Formule le texte d'une demande à envoyer à une institution.
    Le contenu est informatif — la décision d'envoyer appartient à l'orchestrateur.
    """
    client = _get_client()

    prompt = (
        f"Rédige une demande formelle à la {actor_name} "
        f"dans le cadre d'un {case_context.get('use_case', 'changement de situation')}. "
        f"Contexte utilisateur : {case_context.get('user_summary', '')}"
    )

    message = client.messages.create(
        model      = "claude-sonnet-4-20250514",
        max_tokens = 256,
        system     = REQUEST_SYSTEM_PROMPT,
        messages   = [{"role": "user", "content": prompt}]
    )

    return message.content[0].text.strip()


# ── Explication d'un état pour l'utilisateur ────────────────────────────────

EXPLAIN_SYSTEM_PROMPT = """Tu es un assistant de prévoyance suisse qui explique des processus administratifs.
Tu t'adresses à un utilisateur non-expert.
Tu expliques l'état actuel du processus en allemand, de façon claire et rassurante.
Maximum 3 phrases. Pas de jargon technique interne (pas de "state machine", "TIMEOUT", etc.).
"""


def explain_state(actor_name: str, state: str, context: dict) -> str:
    """
    Traduit un état technique en langage compréhensible pour l'utilisateur.
    Pur output formaté — aucune influence sur les transitions.
    """
    client = _get_client()

    state_descriptions = {
        "WAITING":          f"Wir warten auf die Antwort der {actor_name}.",
        "TIMEOUT":          f"Die {actor_name} hat nicht rechtzeitig geantwortet.",
        "CONFLICT_DETECTED": f"Es gibt einen Widerspruch in den Daten der {actor_name}.",
        "HITL_REQUIRED":    f"Deine Eingabe ist erforderlich für die {actor_name}.",
        "ESCALATED":        f"Der Prozess mit der {actor_name} wurde eskaliert.",
        "COMPLETED":        f"Die {actor_name} hat geantwortet und alles ist in Ordnung.",
    }

    description = state_descriptions.get(state, f"Status: {state}")

    message = client.messages.create(
        model      = "claude-sonnet-4-20250514",
        max_tokens = 128,
        system     = EXPLAIN_SYSTEM_PROMPT,
        messages   = [{
            "role": "user",
            "content": f"{description} Erkläre dem Nutzer kurz, was das bedeutet."
        }]
    )

    return message.content[0].text.strip()


# ── Résumé final du cas ──────────────────────────────────────────────────────

SUMMARY_SYSTEM_PROMPT = """Tu es un assistant de prévoyance suisse.
Tu rédiges un résumé final du processus pour l'utilisateur, en allemand.
Sois clair, positif si possible, et indique les prochaines étapes si nécessaire.
Maximum 5 phrases.
"""


def generate_case_summary(case_summary: dict) -> str:
    """
    Génère un résumé final lisible du cas pour l'utilisateur.
    Appelé après AGGREGATION, avant USER_VALIDATION.
    """
    client = _get_client()

    message = client.messages.create(
        model      = "claude-sonnet-4-20250514",
        max_tokens = 256,
        system     = SUMMARY_SYSTEM_PROMPT,
        messages   = [{
            "role": "user",
            "content": f"Erstelle eine Zusammenfassung für den Nutzer basierend auf: {json.dumps(case_summary, ensure_ascii=False)}"
        }]
    )

    return message.content[0].text.strip()

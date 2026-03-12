# HelveVista — Prototype V2

Agentischer digitaler Vermittler im Schweizer Altersvorsorgesystem.
Bachelor-Arbeit, ZHAW — Modell V2 (Stellenwechsel)

## Architektur

```
helvevista/
├── core/                         # Kontrolllogik (deterministisch)
│   ├── states.py                 # États : OrchestratorState, ActorState, Actor
│   ├── event_log.py              # Event Log append-only (Source of Truth)
│   ├── actor_process.py          # Mini-state-machine par acteur institutionnel
│   └── orchestrator.py           # Orchestrateur principal
├── llm/                          # Composante LLM (non-déterministe)
│   └── structurer.py             # Anthropic Claude API — structurer / formuler
├── tests/
│   └── test_stellenwechsel.py    # Validation H1 (Safety) et H2 (Liveness)
├── data/                         # Event logs persistés (JSON Lines)
└── main.py                       # Point d'entrée / démo interactive
```

## Principe fondamental (Modèle V2, §11)

```
┌─────────────────────────────────────────────────────────┐
│  COUCHE CONTRÔLE (core/)          COUCHE LLM (llm/)     │
│  ─ déterministe                   ─ non-déterministe     │
│  ─ state machine                  ─ structurer           │
│  ─ event log                      ─ extraire             │
│  ─ transitions                    ─ formuler             │
│                                   ─ expliquer            │
│  ❌ LLM ne change jamais un état                         │
│  ❌ LLM ne décide jamais une transition                  │
└─────────────────────────────────────────────────────────┘
```

## Installation

```bash
pip install anthropic
```

## Lancement

```bash
# Démo simulée (sans API key)
python main.py

# Avec LLM réel
export ANTHROPIC_API_KEY=sk-ant-...
python main.py
```

## Tests (H1 + H2)

```bash
python tests/test_stellenwechsel.py

# ou avec pytest
pip install pytest
python -m pytest tests/ -v
```

## Use Case : Stellenwechsel

```
INIT → STRUCTURED → CONDITIONAL_FORK
                         ├── OLD_PK : REQUEST → WAITING → RESPONSE → COMPLETED
                         ├── NEW_PK : REQUEST → WAITING → RESPONSE → COMPLETED
                         └── AVS    : (optionnel) REQUEST → WAITING → COMPLETED
                    ↓
               AGGREGATION → USER_VALIDATION → CLOSED_SUCCESS
                                             → CLOSED_ESCALATED
                                             → CLOSED_ABORTED
```

## Hypothèses validées par les tests

| Hypothèse | Description | Test |
|-----------|-------------|------|
| H1 Safety | Versionsprüfung bloque les données obsolètes | `test_version_conflict()` |
| H2 Liveness | Timeout + Escalation évitent les deadlocks | `test_timeout_escalation()` |

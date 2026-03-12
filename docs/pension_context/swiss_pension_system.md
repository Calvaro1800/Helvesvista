# Swiss Pension System — Context

Background documentation for the HelveVista use case.

---

## Three-Pillar Structure

| Pillar | Name | Type | Institution |
|--------|------|------|-------------|
| 1st | AHV / AVS | Mandatory, state-run | AHV compensation offices |
| 2nd | BVG / LPP | Mandatory, employer-run | Pensionskassen (PK) |
| 3rd | Säule 3a/3b | Voluntary, private | Banks, insurance companies |

## Key Statistics (BSV, 2024)

- 2.546 million old-age pension recipients
- CHF 50.0 billion in AHV expenditures (2023)
- CHF 51.2 billion in AHV revenues (2023)
- 1,749 million AHV insured in Switzerland, 796,000 abroad

## The Stellenwechsel Problem

When an employee changes jobs in Switzerland:

1. **Alte PK** must calculate and transfer Freizügigkeitsleistung
2. **Neue PK** must receive and apply the transferred capital
3. **AVS** may need to provide an IK-Auszug (individual account statement)
4. **Bank** may be involved for Säule 3a coordination (optional)
5. **Employer** confirms payroll deductions

These actors:
- Have no shared data infrastructure
- Operate on independent timelines (days to weeks)
- Respond asynchronously
- May provide contradictory or outdated information

**Typical duration:** 4–8 weeks for a complete, well-coordinated Stellenwechsel.

## Coordination Problem (Malone & Crowston, 1994)

The Stellenwechsel is a canonical example of inter-organizational coordination:
- Multiple actors with shared dependencies
- No central authority
- Temporal decoupling
- Information asymmetry

HelveVista addresses this as a **coordination technology** (Malone & Crowston, 1994)
implemented as an agentic digital intermediary.

## Existing Digital Solutions and Their Limits

| Solution | Scope | Category (Hosseini & Seilani, 2025) |
|----------|-------|--------------------------------------|
| PK Portal | Single institution | Copilot |
| BSV Rentenrechner | AHV only | Copilot |
| Banking App | Säule 3a only | Copilot |
| FAQ Chatbot | Single institution | Copilot |
| **HelveVista** | All three pillars, multilateral | **Autopilot (target)** |

None of the existing solutions addresses cross-institutional, asynchronous coordination.

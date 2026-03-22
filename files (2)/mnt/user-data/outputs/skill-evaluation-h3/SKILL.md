# SKILL — H3 Evaluation for HelveVista

## Overview

This skill defines how to implement the H3 evaluation within HelveVista.

**H3 (Kompetenz):**
> Nutzende, die einen Vorsorgeprozess durch HelveVista strukturiert begleitet werden,
> schätzen ihr Verständnis des eigenen Vorsorgeprozesses nach der Interaktion
> signifikant höher ein als zuvor.

**Method:** Pre-Post-Befragung with 5-10 real users
**Theoretical anchor:** PLV UZH (2024), TAM (Davis, 1989), Akzeptanz + Perceived Support

---

## Evaluation Design

### Pre-Survey (before using HelveVista)
Administered before the user interacts with HelveVista.
Measures baseline understanding and confidence.

### Post-Survey (after using HelveVista)
Administered immediately after completing the Stellenwechsel scenario.
Measures change in understanding and perceived support.

---

## Questionnaire — Pre-Survey

```python
PRE_SURVEY_QUESTIONS = [
    {
        "id": "pre_1",
        "text": "Wie gut verstehen Sie den Ablauf eines Stellenwechsels "
                "in Bezug auf Ihre Pensionskasse?",
        "type": "scale",
        "scale": (1, 5),
        "labels": {1: "Gar nicht", 3: "Mittelmässig", 5: "Sehr gut"}
    },
    {
        "id": "pre_2",
        "text": "Wissen Sie, welche Institutionen bei einem Stellenwechsel "
                "involviert sind?",
        "type": "scale",
        "scale": (1, 5),
        "labels": {1: "Nein", 3: "Teilweise", 5: "Ja, vollständig"}
    },
    {
        "id": "pre_3",
        "text": "Wie sicher fühlen Sie sich, einen Stellenwechsel in Bezug "
                "auf Ihre Vorsorge selbständig zu koordinieren?",
        "type": "scale",
        "scale": (1, 5),
        "labels": {1: "Sehr unsicher", 3: "Neutral", 5: "Sehr sicher"}
    },
    {
        "id": "pre_4",
        "text": "Haben Sie schon einmal einen Stellenwechsel mit "
                "Pensionskassenwechsel erlebt?",
        "type": "choice",
        "options": ["Ja", "Nein", "Ich weiss es nicht mehr"]
    },
    {
        "id": "pre_5",
        "text": "Was war dabei das Schwierigste?",
        "type": "text",
        "optional": True
    }
]
```

---

## Questionnaire — Post-Survey

```python
POST_SURVEY_QUESTIONS = [
    {
        "id": "post_1",
        "text": "Wie gut verstehen Sie jetzt den Ablauf eines Stellenwechsels "
                "in Bezug auf Ihre Pensionskasse?",
        "type": "scale",
        "scale": (1, 5),
        "labels": {1: "Gar nicht", 3: "Mittelmässig", 5: "Sehr gut"}
    },
    {
        "id": "post_2",
        "text": "Hat HelveVista Ihnen geholfen zu verstehen, welche "
                "Institutionen involviert sind?",
        "type": "scale",
        "scale": (1, 5),
        "labels": {1: "Gar nicht", 3: "Teilweise", 5: "Vollständig"}
    },
    {
        "id": "post_3",
        "text": "Fühlen Sie sich nach der Nutzung von HelveVista sicherer, "
                "einen solchen Prozess zu koordinieren?",
        "type": "scale",
        "scale": (1, 5),
        "labels": {1: "Nein, nicht sicherer", 3: "Etwas sicherer", 5: "Viel sicherer"}
    },
    {
        "id": "post_4",
        "text": "HelveVista hat mich während des gesamten Prozesses "
                "gut unterstützt. (Perceived Support)",
        "type": "scale",
        "scale": (1, 5),
        "labels": {1: "Stimme nicht zu", 3: "Neutral", 5: "Stimme vollständig zu"}
    },
    {
        "id": "post_5",
        "text": "Die Nutzung von HelveVista war einfach und verständlich. "
                "(Perceived Ease of Use — TAM)",
        "type": "scale",
        "scale": (1, 5),
        "labels": {1: "Stimme nicht zu", 3: "Neutral", 5: "Stimme vollständig zu"}
    },
    {
        "id": "post_6",
        "text": "Ich würde HelveVista für zukünftige Vorsorgeprozesse "
                "empfehlen. (Perceived Usefulness — TAM)",
        "type": "scale",
        "scale": (1, 5),
        "labels": {1: "Nein", 3: "Vielleicht", 5: "Ja, definitiv"}
    },
    {
        "id": "post_7",
        "text": "Was hat Ihnen an HelveVista am besten gefallen?",
        "type": "text",
        "optional": True
    },
    {
        "id": "post_8",
        "text": "Was würden Sie verbessern?",
        "type": "text",
        "optional": True
    }
]
```

---

## Streamlit Survey Renderer

```python
def render_survey(questions: list, key_prefix: str) -> dict:
    """Render survey questions and collect responses."""
    responses = {}

    for q in questions:
        st.write(f"**{q['text']}**")

        if q["type"] == "scale":
            low, high = q["scale"]
            labels = q.get("labels", {})
            label_str = " — ".join(
                f"{k}: {v}" for k, v in sorted(labels.items())
            )
            st.caption(label_str)

            response = st.slider(
                "",
                min_value=low,
                max_value=high,
                value=(low + high) // 2,
                key=f"{key_prefix}_{q['id']}"
            )
            responses[q["id"]] = response

        elif q["type"] == "choice":
            response = st.radio(
                "",
                q["options"],
                key=f"{key_prefix}_{q['id']}"
            )
            responses[q["id"]] = response

        elif q["type"] == "text":
            optional_label = " (optional)" if q.get("optional") else ""
            response = st.text_area(
                f"Ihre Antwort{optional_label}",
                key=f"{key_prefix}_{q['id']}"
            )
            responses[q["id"]] = response

        st.divider()

    return responses
```

---

## Results Analysis

```python
def calculate_delta(pre: dict, post: dict) -> dict:
    """Calculate improvement between pre and post survey."""
    paired_questions = {
        "Prozessverständnis": ("pre_1", "post_1"),
        "Akteurkenntnis":     ("pre_2", "post_2"),
        "Selbstsicherheit":   ("pre_3", "post_3"),
    }

    deltas = {}
    for label, (pre_key, post_key) in paired_questions.items():
        if pre_key in pre and post_key in post:
            delta = post[post_key] - pre[pre_key]
            deltas[label] = {
                "pre": pre[pre_key],
                "post": post[post_key],
                "delta": delta,
                "improved": delta > 0
            }
    return deltas


def render_results(deltas: dict, post: dict):
    """Render evaluation results visually."""
    st.subheader("Evaluationsergebnisse")

    # Delta metrics
    cols = st.columns(len(deltas))
    for col, (label, data) in zip(cols, deltas.items()):
        with col:
            delta_str = f"+{data['delta']}" if data['delta'] > 0 else str(data['delta'])
            st.metric(
                label=label,
                value=f"{data['post']}/5",
                delta=delta_str
            )

    st.divider()

    # TAM metrics
    st.subheader("Technology Acceptance (TAM)")
    tam_cols = st.columns(3)
    with tam_cols[0]:
        st.metric("Perceived Support", f"{post.get('post_4', 0)}/5")
    with tam_cols[1]:
        st.metric("Ease of Use", f"{post.get('post_5', 0)}/5")
    with tam_cols[2]:
        st.metric("Usefulness", f"{post.get('post_6', 0)}/5")
```

---

## Data Storage

```python
import json
from datetime import datetime

def save_evaluation(user_id: str, pre: dict, post: dict, session_id: str):
    """Save evaluation data to JSON file."""
    data = {
        "user_id": user_id,
        "session_id": session_id,
        "timestamp": datetime.now().isoformat(),
        "pre_survey": pre,
        "post_survey": post,
        "deltas": calculate_delta(pre, post)
    }

    filename = f"evaluation_data/{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    os.makedirs("evaluation_data", exist_ok=True)

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return filename
```

---

## Integration in user_app.py

```python
# Before HelveVista — show pre-survey
if st.session_state.step == 0:
    st.title("Kurze Befragung vor der Nutzung")
    st.write("Bevor Sie beginnen, bitten wir Sie um 2 Minuten Ihrer Zeit.")
    pre_responses = render_survey(PRE_SURVEY_QUESTIONS, "pre")
    if st.button("Weiter zu HelveVista →"):
        st.session_state.pre_survey = pre_responses
        st.session_state.step = 1
        st.rerun()

# After HelveVista — show post-survey
if st.session_state.step == 7:
    st.title("Kurze Befragung nach der Nutzung")
    post_responses = render_survey(POST_SURVEY_QUESTIONS, "post")
    if st.button("Auswertung anzeigen"):
        st.session_state.post_survey = post_responses
        st.session_state.step = 8
        st.rerun()

# Show results
if st.session_state.step == 8:
    deltas = calculate_delta(
        st.session_state.pre_survey,
        st.session_state.post_survey
    )
    render_results(deltas, st.session_state.post_survey)
```

---

## What NOT to do

- ❌ Never collect real personal data — user_id should be anonymous
- ❌ Never skip the pre-survey — delta measurement requires baseline
- ❌ Never force answers on optional text questions
- ❌ Never show individual results to other users
- ❌ Never use this data for anything other than H3 validation

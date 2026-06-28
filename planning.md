# Provenance Guard — Architecture Planning

## Architecture Narrative

A piece of text enters the system via `POST /submit`. The API layer validates the payload — confirming the `text` field is present and within the 50,000-character limit. It then passes the raw text to the **Detector**, which runs two independent statistical signals on it.

**Signal 1 (Vocabulary Richness)** tokenizes the text and computes how varied the vocabulary is relative to the total word count. The resulting score is a number from 0 to 1 where higher means more AI-like.

**Signal 2 (Sentence Burstiness)** splits the text into sentences, measures each sentence's word count, and computes the coefficient of variation across those lengths. A lower CoV means more uniform sentences, which is more AI-like; the signal is inverted so higher still means more AI-like.

The **Confidence Scorer** combines both signal scores into a single `confidence` value (0.0 = certainly human, 1.0 = certainly AI) using a weighted average. The **Label Generator** maps that value to a human-readable transparency label ("Likely Human-Written", "Uncertain - May Be Human or AI", "Likely AI-Assisted", "Very Likely AI-Generated").

The result is written to the **Storage layer** (in-memory dict) and two events are written to the **Audit Logger** — one for the submission, one for the analysis. The API returns the `submission_id`, `confidence`, `label`, signal breakdown, and status to the caller.

When a creator disputes a classification, they `POST /appeal/{submission_id}` with a `reason`. The API fetches the record from Storage, flips its `status` to `under_review`, and appends an `appeal_submitted` event to the Audit Log. The caller receives confirmation and the updated status.

---

## Detection Signals

### Signal 1: Vocabulary Richness (Root Type-Token Ratio)

**What it measures:** The ratio of unique words to total words, normalized for text length using the square root of the token count (Root TTR). A high RTTR means the author draws from a wide, varied vocabulary.

**Why it differs:** LLMs are trained to minimize perplexity — they gravitate toward the most probable next token, which means they repeatedly reach for the same high-frequency words. Human writers, especially under emotional or creative pressure, pull from a wider, less predictable lexicon. AI-generated paragraphs often score lower on RTTR because the same safe connectors and transitions recur constantly.

**Blind spot:** Technical writing, legal boilerplate, and medical reports use domain-specific terminology at high frequency by necessity — a human-written clinical summary might score as AI-like because "patient," "dose," and "administered" appear constantly. Short texts (< 50 words) also produce unreliable RTTR values.

---

### Signal 2: Sentence Length Burstiness (Coefficient of Variation)

**What it measures:** The standard deviation of sentence lengths (in words) divided by the mean. A high coefficient of variation means the text mixes very short and very long sentences — high burstiness.

**Why it differs:** Human writers vary sentence rhythm naturally — a short punch after a long clause, a one-word fragment for emphasis. Current LLMs tend to produce sentences that cluster around a comfortable medium length (12–20 words), resulting in low variance. Burstiness is one of the most stable stylometric signals for distinguishing AI prose.

**Blind spot:** Legal contracts and academic abstracts deliberately use uniform sentence structure — a human-written statute will score as AI-like. Stream-of-consciousness writing (Woolf, Kerouac) can produce high burstiness that looks human, but a very formal LLM output with explicit length instructions can match it too. Poems and bulleted lists break the sentence-splitting heuristic entirely.

---

## False Positive Scenario

A novelist submits their own short story. The story uses recurring motifs ("the bridge," "the dark water") which lowers vocabulary richness. The story is written in a deliberately restrained style with uniform sentence lengths for atmospheric effect. Both signals score high AI-likelihood, and the confidence lands at 0.72 — "Very Likely AI-Generated."

The confidence score reflects this uncertainty honestly: 0.72 is not 0.99. The label chosen ("Very Likely AI-Generated") is accurate to the score but still a misclassification. The creator reads the label and the confidence value, understands the system flagged them, and submits an appeal via `POST /appeal/{id}` with a reason explaining their stylistic choices. The status moves to `under_review`. Every step — original analysis, appeal submission — is in the audit log, so a human reviewer can trace exactly what happened.

This scenario informed two design decisions: (1) always expose `confidence` numerically alongside the label so the degree of certainty is visible, and (2) keep the appeal path simple and immediate rather than gating it on thresholds.

---

## API Surface

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/submit` | Submit text for analysis; returns classification |
| `GET`  | `/status/<submission_id>` | Retrieve current classification and status |
| `POST` | `/appeal/<submission_id>` | Dispute a classification with a written reason |
| `GET`  | `/audit/<submission_id>` | Full event log for a submission |
| `GET`  | `/health` | Liveness check |

### Request / Response Contracts

**POST /submit**
```
Request:  { "text": string, "creator_id": string }
Response: { "submission_id": uuid, "confidence": float, "label": string,
            "signals": { "vocabulary_richness": float, "sentence_burstiness": float },
            "status": "reviewed", "created_at": iso8601 }
```

**GET /status/<id>**
```
Response: { "submission_id": uuid, "confidence": float, "label": string,
            "signals": {...}, "status": string, "creator_id": string, "created_at": iso8601 }
```

**POST /appeal/<id>**
```
Request:  { "reason": string, "creator_id": string }
Response: { "submission_id": uuid, "status": "under_review", "message": string }
```

**GET /audit/<id>**
```
Response: { "submission_id": uuid, "events": [ { "event": string, "timestamp": iso8601, ...detail } ] }
```

---

## System Flow Diagrams

### Submission Flow

```
Client
  |
  |  POST /submit  { text, creator_id }
  v
+---------------------------+
|   API Layer (Flask)       |
|   validate input          |
+---------------------------+
  |              |
  | text         | text
  v              v
+------------+  +-------------------+
| Signal 1   |  | Signal 2          |
| Vocabulary |  | Sentence          |
| Richness   |  | Burstiness        |
| (Root TTR) |  | (CoV of lengths)  |
+------------+  +-------------------+
  |                    |
  | vocab_score (0-1)  | burst_score (0-1)
  +--------+-----------+
           |
           v
  +---------------------+
  | Confidence Scorer   |
  | 0.5 * vocab_score   |
  | + 0.5 * burst_score |
  +---------------------+
           |
           | confidence (0.0 – 1.0)
           v
  +------------------+
  | Label Generator  |   < 0.30 → "Likely Human-Written"
  |                  |   < 0.50 → "Uncertain - May Be Human or AI"
  |                  |   < 0.70 → "Likely AI-Assisted"
  |                  |   >= 0.70 → "Very Likely AI-Generated"
  +------------------+
           |
           | label, confidence, signals
           v
  +------------------+
  | Storage (dict)   |  ← record keyed by submission_id
  +------------------+
           |
           v
  +------------------+
  | Audit Logger     |  ← event: "submitted"
  |                  |  ← event: "analyzed"
  +------------------+
           |
           v
  Response: { submission_id, confidence, label, signals, status, created_at }
```

### Appeal Flow

```
Client
  |
  |  POST /appeal/<submission_id>  { reason, creator_id }
  v
+---------------------------+
|   API Layer (Flask)       |
|   validate input          |
+---------------------------+
           |
           v
  +------------------+
  | Storage Lookup   |  → 404 if submission_id not found
  +------------------+
           |
           | record found
           v
  +---------------------------+
  | Status Updater            |
  | status: "reviewed"        |
  |      → "under_review"     |
  +---------------------------+
           |
           v
  +------------------+
  | Audit Logger     |  ← event: "appeal_submitted" { reason, creator_id }
  +------------------+
           |
           v
  Response: { submission_id, status: "under_review", message }
```

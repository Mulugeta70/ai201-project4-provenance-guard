# Provenance Guard — Planning Specification

---

## 1. Detection Signals

### Signal 1: Vocabulary & Formality Analysis (composite of 3 sub-metrics)

**What it measures:**
A composite of three sub-metrics that together capture how formal, academic, and lexically homogeneous the writing is. All three sub-scores are in `[0, 1]` (higher = more AI-like) and averaged with equal weight.

*Sub-metric 1 — Root TTR (lexical diversity):* ratio of unique words to total words, normalized by `sqrt(N)`. Low diversity → AI-like.

*Sub-metric 2 — Average word length:* AI-generated text gravitates toward polysyllabic formal vocabulary ("transformative," "implications," "deployment"). Casual human writing uses shorter words ("ok," "fine," "ramen"). Mapped linearly: avg_len 3 → 0.0; avg_len 8+ → 1.0.

*Sub-metric 3 — Long-word density:* fraction of words ≥ 7 characters. Academic and AI prose packs in polysyllabic vocabulary; colloquial human writing avoids it. Mapped: density 40%+ → 1.0.

**Why the composite beats Root TTR alone:**
Root TTR alone is poorly discriminative for short texts (< 100 words) because even AI-generated text uses varied vocabulary in a single paragraph — there simply aren't enough repetitions to suppress TTR. At 50 words, AI and human texts land at nearly identical RTTR values. Average word length and long-word density are stable even at 40 words and correctly separate a formal AI paragraph from a casual human anecdote.

**Output format:**
A float in `[0.0, 1.0]`. Higher means more AI-like. Computed as:

```
words        = tokenize(text, pattern=r'\b[a-zA-Z]+\b')
rttr         = (len(unique(words)) / len(words)) * sqrt(len(words))
rttr_score   = 1 / (1 + rttr / 4)
avg_len      = mean(len(w) for w in words)
len_score    = clamp((avg_len - 3.0) / 5.0, 0, 1)
long_density = count(w for w in words if len(w) >= 7) / len(words)
density_score= min(long_density * 2.5, 1.0)
vocab_score  = (rttr_score + len_score + density_score) / 3
```

If the text has fewer than 10 words, the function returns `0.5` (neutral, not enough data).

**Calibration results (Milestone 4 test cases):**

| Input | vocab_score |
|---|---|
| Clearly AI-generated (formal paragraph) | 0.685 |
| Borderline formal human writing | 0.667 |
| Lightly edited AI output | 0.502 |
| Clearly human-written (casual) | 0.324 |

**Blind spot:**
Formal academic writing by humans (economics papers, legal briefs) will score as AI-like because it shares the same vocabulary properties. The signal cannot distinguish formal-by-training from formal-by-stylistic-choice. Very short texts (< 30 words) remain unreliable.

---

### Signal 2: Sentence Length Burstiness (Coefficient of Variation)

**What it measures:**
The coefficient of variation (CoV) of sentence lengths in words — that is, the standard deviation divided by the mean. A high CoV means the text mixes very short and very long sentences (bursty). A low CoV means sentences cluster around a uniform length (flat).

**Why it differs between human and AI writing:**
Human writers vary sentence rhythm naturally — a short punch after a long clause, a one-word fragment for emphasis, a sprawling run-on when thoughts cascade. This produces high sentence-length variance. Current LLMs, absent explicit instructions, tend to produce sentences that cluster around a comfortable medium length (roughly 12–20 words per sentence), yielding low variance. Burstiness is one of the most stable stylometric signals in the literature for distinguishing AI-generated prose.

**Output format:**
A float in `[0.0, 1.0]`. Higher means more AI-like (more uniform). Computed as:

```
sentences = split_on_sentence_boundaries(text)
lengths   = [word_count(s) for s in sentences]
CoV       = stdev(lengths) / mean(lengths)
score     = 1 / (1 + CoV * 2)       # inverse mapping; high CoV → low AI score
```

Calibration reference points:
- CoV ≈ 0.1 (nearly uniform) → score ≈ 0.83
- CoV ≈ 0.5 (moderate variation) → score ≈ 0.50
- CoV ≈ 1.0 (highly varied) → score ≈ 0.33

If the text has fewer than 3 sentences after splitting, the function returns `0.5` (neutral).

**Blind spot:**
Legal contracts and academic abstracts deliberately use uniform sentence structure — a human-written statute will score as AI-like. Single-sentence texts (or texts with only two sentences) cannot have a meaningful standard deviation. Poetry breaks the sentence-splitting heuristic entirely because line breaks and punctuation encode rhythm differently than prose. A bulleted list with items that are all similarly short will score as extremely AI-like regardless of who wrote it.

---

### Combining Signals into Confidence

Both signals return a score in `[0.0, 1.0]` where higher = more AI-like. They are combined as an **equal-weight average**:

```
confidence = 0.5 * vocab_score + 0.5 * burst_score
```

This is rounded to 4 decimal places. The equal weighting reflects that neither signal is known to be more reliable than the other given the current heuristic implementation. If more calibration data becomes available, the weights can be adjusted without changing the combining formula.

---

## 2. Uncertainty Representation

### What a confidence score means

`confidence` is a continuous float in `[0.0, 1.0]`.

- `0.0` would mean both signals simultaneously scored the text as perfectly human-like — maximally varied vocabulary, maximally bursty sentence rhythm. No real text reaches this.
- `1.0` would mean both signals simultaneously scored the text as maximally AI-like — zero vocabulary diversity, perfectly uniform sentence lengths. No real text reaches this either.
- `0.6` means the averaged signal output leans toward AI patterns but not strongly. At least one signal found something human-like. The system is more likely correct than not, but not confident enough to state a definitive verdict. The appropriate label is "Likely AI-Assisted" — a hedge, not a conviction.

### Threshold mapping

| Confidence range | Label |
|---|---|
| `0.00 – 0.29` | Likely Human-Written |
| `0.30 – 0.49` | Uncertain — May Be Human or AI |
| `0.50 – 0.69` | Likely AI-Assisted |
| `0.70 – 1.00` | Very Likely AI-Generated |

The breakpoints are intentionally asymmetric. "Uncertain" occupies the `0.30–0.49` band rather than `0.40–0.60` because the cost of incorrectly labeling a human writer as "Likely AI-Assisted" is higher than the cost of being uncertain. Pushing the uncertain zone lower means the system is reluctant to claim human authorship without meaningful signal.

### How raw signal scores map to calibrated confidence

No additional calibration layer is applied in this implementation. The signal functions are designed so that their outputs land in `[0.0, 1.0]` via inverse mappings that reflect the expected distributions. The combined average therefore also lands in `[0.0, 1.0]`. The thresholds above were selected by manual calibration against a small set of test cases (clearly human writing, clearly AI writing, mixed) to confirm the four tiers are all reachable and that the uncertain band is reached on ambiguous inputs.

---

## 3. Transparency Label Design

These are the exact strings the system returns in the `label` field. They are chosen to be:
- Factual, not accusatory
- Consistent in structure (statement + implication)
- Usable without additional context

### Label 1 — High-confidence human result (confidence < 0.30)

```
"Likely Human-Written"
```

Interpretation surfaced to the user: This content shows characteristics consistent with human authorship — varied vocabulary and varied sentence rhythm. Confidence: [score].

### Label 2 — Uncertain result (0.30 ≤ confidence < 0.50)

```
"Uncertain — May Be Human or AI"
```

Interpretation surfaced to the user: This content shows mixed signals. It may be human-written, AI-generated, or AI-assisted in some parts. The system cannot determine origin with confidence. Confidence: [score].

### Label 3 — Moderate AI confidence (0.50 ≤ confidence < 0.70)

```
"Likely AI-Assisted"
```

Interpretation surfaced to the user: This content shows patterns that commonly appear in AI-generated text. It may be fully AI-generated or heavily AI-edited. Confidence: [score].

### Label 4 — High-confidence AI result (confidence ≥ 0.70)

```
"Very Likely AI-Generated"
```

Interpretation surfaced to the user: This content strongly matches statistical patterns of AI-generated text — low vocabulary diversity and uniform sentence lengths. Confidence: [score].

**Design note:** Four labels, not three. Three felt like a false compromise — "likely AI" and "very likely AI" are meaningfully different responses and collapsing them loses useful signal. The creator at 0.72 and the creator at 0.97 should not see the same label.

---

## 4. Appeals Workflow

### Who can submit an appeal

Any caller who knows the `submission_id`. In this implementation there is no authentication layer — the `creator_id` field is caller-supplied and used for audit purposes only. The practical constraint is that you need the `submission_id` returned at submit time, which functions as a shared secret for the creator.

### What information an appeal requires

```json
{
  "reason": "string (required, non-empty)",
  "creator_id": "string (optional, defaults to 'anonymous')"
}
```

The `reason` must be a non-empty string. The system does not validate the content of the reason — any non-blank text is accepted. This is intentional: gatekeeping on reason quality adds friction without improving accuracy.

### What the system does when an appeal is received

1. Look up the submission by `submission_id`. Return 404 if not found.
2. Set `status` from `"reviewed"` to `"under_review"`. Store the `appeal_reason` on the record.
3. Append an `appeal_submitted` event to the audit log with `creator_id`, `reason`, and `timestamp`.
4. Return `{ submission_id, status: "under_review", message }` to the caller.

The original `confidence` and `label` are **not changed** at appeal time. The record preserves the original classification so a reviewer can compare it to the appeal reason. Overwriting the label before human review would defeat the audit trail.

### What a human reviewer sees

A reviewer examining `GET /audit/<submission_id>` sees the full event timeline:

```json
{
  "submission_id": "...",
  "events": [
    { "event": "submitted",       "timestamp": "...", "creator_id": "...", "text_length": 843 },
    { "event": "analyzed",        "timestamp": "...", "confidence": 0.72, "label": "Very Likely AI-Generated" },
    { "event": "appeal_submitted","timestamp": "...", "creator_id": "...", "reason": "This is my novel draft, chapter 3." }
  ]
}
```

Combined with `GET /status/<submission_id>`, the reviewer sees the current label, the confidence score, the individual signal scores (`vocabulary_richness`, `sentence_burstiness`), and the stated reason for appeal. They have everything needed to make a determination: the classification, the raw signal evidence, and the creator's argument.

---

## 5. Anticipated Edge Cases

### Edge case 1: Poetry with deliberate repetition

A poet submits a villanelle — a form that requires two lines to repeat six times across 19 lines. The recurring lines tank vocabulary richness (high repetition of exact phrases). The fixed-form stanzas also produce near-uniform line lengths in words, which tanks the burstiness signal. The poem is deeply human — the repetition is the form — but both signals fire strongly. Expected outcome: confidence ~0.75, label "Very Likely AI-Generated" for a piece that is categorically human.

**Mitigation in system design:** The confidence score (0.75) is not 0.95. The numeric value is exposed in the response alongside the label, so a reviewer can see the system's uncertainty is bounded. The creator can appeal with "this is a villanelle, a fixed form that requires repetition." The audit log captures this.

### Edge case 2: Very short text (under 30 words)

A creator submits a tweet-length piece: "Just finished the report. Tired but proud. The numbers tell a story." This is 13 words across 3 sentences. The vocabulary TTR for 13 words is inherently unstable — almost all words will be unique. The CoV of 3 sentence lengths is meaningful but noisy at this sample size. Both signals default to `0.5` (neutral) when below the minimum threshold, so confidence returns as `0.5` and the label is "Likely AI-Assisted" — not a meaningless result, but not a confident one either.

**What this tells us:** The system systematically under-detects on short content. Short AI-generated text will often escape classification. This is the correct tradeoff — it is better to say "uncertain" than to confidently misclassify at low N.

### Edge case 3: AI-generated text explicitly instructed to vary vocabulary

A user prompts an LLM with "write in a diverse, colloquial style with varied sentence lengths and unusual word choices." The output may score low on both AI signals. Both heuristics measure surface statistical properties, not semantic coherence or factual accuracy. A carefully prompted LLM can produce text that defeats both signals simultaneously. The system will return "Likely Human-Written" or "Uncertain" — a false negative.

**What this tells us:** Statistical surface signals have a fundamental ceiling. An adversarial actor with knowledge of the signals can engineer around them. This is a known limitation of heuristic detection, not a bug to fix.

---

## Architecture

### Narrative

A piece of text arrives at `POST /submit`. The API layer validates it (non-empty, ≤ 50,000 characters) and passes the raw text to the Detector, which runs both statistical signals independently and combines their outputs into a single confidence score. The Label Generator maps that score to a tier. The Storage layer saves the complete record, the Audit Logger appends two timestamped events (one for the submission, one for the analysis result), and the API returns the classification to the caller.

When a creator disputes a result, `POST /appeal/<id>` looks up the record, transitions its status to `under_review`, logs an appeal event with the stated reason, and returns confirmation. The original confidence and label are preserved unchanged — a human reviewer uses `GET /audit/<id>` to see the complete event timeline and make a determination.

### Submission Flow

```
Client
  |
  |  POST /submit  { text, creator_id }
  v
+---------------------------+
|   API Layer (Flask)       |
|   validate: non-empty,    |
|   len <= 50,000 chars     |
+---------------------------+
  |              |
  | text         | text
  v              v
+------------------+  +---------------------+
| Signal 1         |  | Signal 2            |
| Vocabulary       |  | Sentence Burstiness |
| Richness         |  | (CoV of lengths)    |
| (Root TTR)       |  |                     |
| → float [0,1]    |  | → float [0,1]       |
+------------------+  +---------------------+
        |                       |
        | vocab_score           | burst_score
        +----------+------------+
                   |
                   v
        +---------------------+
        | Confidence Scorer   |
        | conf = 0.5*v + 0.5*b|
        | → float [0,1]       |
        +---------------------+
                   |
                   | confidence
                   v
        +----------------------+
        | Label Generator      |
        | < 0.30 → Human       |
        | < 0.50 → Uncertain   |
        | < 0.70 → AI-Assisted |
        | >= 0.70 → Very Likely|
        +----------------------+
                   |
                   | label + all scores
                   v
        +------------------+
        | Storage (dict)   |  keyed by submission_id (uuid4)
        +------------------+
                   |
                   v
        +------------------+
        | Audit Logger     |  event: "submitted"
        |                  |  event: "analyzed"
        +------------------+
                   |
                   v
        Response 201: {
          submission_id, confidence, label,
          signals: {vocabulary_richness, sentence_burstiness},
          status: "reviewed", created_at
        }
```

### Appeal Flow

```
Client
  |
  |  POST /appeal/<submission_id>  { reason, creator_id }
  v
+---------------------------+
|   API Layer (Flask)       |
|   validate: reason present|
+---------------------------+
           |
           v
  +------------------+
  | Storage Lookup   |  → 404 if not found
  +------------------+
           |
           | record found
           v
  +---------------------------+
  | Status Updater            |
  | "reviewed" → "under_review"|
  | store appeal_reason        |
  +---------------------------+
           |
           v
  +------------------+
  | Audit Logger     |  event: "appeal_submitted"
  |                  |  { creator_id, reason, timestamp }
  +------------------+
           |
           v
  Response 200: {
    submission_id,
    status: "under_review",
    message: "Your appeal has been received..."
  }
```

---

## AI Tool Plan

### M3 — Submission endpoint + Signal 1 (vocabulary richness)

**Spec sections to provide to the AI tool:**
- Section 1 (Detection Signals) — Signal 1 only, including the RTTR formula, output format, and calibration reference points
- Architecture diagram — submission flow only

**What to ask for:**
Generate a Flask application skeleton with `POST /submit` and `GET /health`. The `/submit` handler should call a `analyze(text)` function that returns `vocab_score`, `burst_score` (placeholder 0.5), `confidence`, and `label`. Implement the `_vocabulary_ai_score(text)` function using Root TTR with the inverse mapping formula provided. Include in-memory storage using a dict and uuid4 for submission IDs.

**How to verify before wiring:**
Call `_vocabulary_ai_score()` directly on three inputs:
1. Short text (< 10 words) → expect return of `0.5`
2. High-repetition text (same sentence repeated 10 times) → expect score > `0.55`
3. Long text with varied vocabulary (any novel excerpt) → expect score < `0.40`

Only wire into the endpoint after all three behave as expected.

---

### M4 — Signal 2 + confidence scoring

**Spec sections to provide to the AI tool:**
- Section 1 (Detection Signals) — Signal 2, including the CoV formula, output format, and calibration reference points
- Section 2 (Uncertainty Representation) — threshold table and combining formula
- Architecture diagram — confidence scorer and label generator boxes

**What to ask for:**
Implement `_burstiness_ai_score(text)` using CoV with the inverse mapping formula. Replace the placeholder `0.5` burst score in the existing `analyze()` function with the real implementation. Add the label mapping function using the exact thresholds and label strings from Section 3. Wire both into the confidence combining formula `0.5 * vocab + 0.5 * burst`.

**How to verify before moving on:**
Run `analyze()` on:
1. Clearly AI-sounding text (flat, formal, uniform sentences all 15–18 words long, repeated vocabulary) → expect confidence > `0.60`
2. Clearly human-sounding text (short punchy sentences mixed with long ones, varied word choice, colloquial) → expect confidence < `0.40`
3. A text with exactly 2 sentences → expect burst_score of `0.5` (below minimum sentence count)

If the scores don't separate the AI vs. human samples, revisit the inverse mapping constants.

---

### M5 — Production layer (labels, appeals, audit)

**Spec sections to provide to the AI tool:**
- Section 3 (Transparency Label Design) — all four label strings verbatim
- Section 4 (Appeals Workflow) — the full workflow: who, what info, what happens on receipt, what reviewer sees
- Architecture diagram — appeal flow

**What to ask for:**
Implement the remaining three endpoints: `GET /status/<submission_id>`, `POST /appeal/<submission_id>`, and `GET /audit/<submission_id>`. The appeal handler must: validate that `reason` is non-empty, transition `status` to `"under_review"`, store `appeal_reason` on the record, and append an `appeal_submitted` audit event. The audit endpoint must return the full event list in insertion order.

**How to verify:**
1. Submit text → confirm all four label tiers are reachable by varying the input text
2. Submit text → call appeal → call status → confirm status is now `"under_review"` and original confidence/label are unchanged
3. Submit text → call audit → confirm exactly two events are present (`submitted`, `analyzed`)
4. Submit text → appeal → audit → confirm exactly three events are present, third is `appeal_submitted` with the correct reason

---

## Label Review

The four label strings are locked before implementation begins:

| Condition | Label string (exact) |
|---|---|
| confidence < 0.30 | `"Likely Human-Written"` |
| 0.30 ≤ confidence < 0.50 | `"Uncertain — May Be Human or AI"` |
| 0.50 ≤ confidence < 0.70 | `"Likely AI-Assisted"` |
| confidence ≥ 0.70 | `"Very Likely AI-Generated"` |

These strings are what `detector.py:_label()` returns and what `app.py` stores in the `label` field of every record. They should not be changed mid-implementation without updating both the spec and the implementation together.

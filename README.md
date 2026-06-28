# Provenance Guard

A Flask API that classifies text as human-written or AI-generated using two
statistical signals, returns a transparency label with a calibrated confidence
score, and supports creator appeals with a full audit trail.

---

## How to Run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
flask --app app run
```

Server starts on `http://localhost:5000`.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/submit` | Analyze text, return classification + content_id |
| `GET`  | `/status/<content_id>` | Current status of a submission |
| `POST` | `/appeal` | File a creator appeal by content_id |
| `GET`  | `/audit/<content_id>` | Full event timeline for a submission |
| `GET`  | `/log` | Recent structured audit log entries |
| `GET`  | `/health` | Liveness check |

### POST /submit

```bash
curl -s -X POST http://localhost:5000/submit \
  -H "Content-Type: application/json" \
  -d '{"text": "Your text here.", "creator_id": "alice"}' | python -m json.tool
```

Response:
```json
{
  "content_id": "3f7a2b1e-...",
  "confidence": 0.60,
  "attribution": "likely_ai",
  "label": "Likely AI-Assisted",
  "signals": {
    "vocabulary_richness": 0.685,
    "sentence_burstiness": 0.518
  },
  "status": "classified",
  "created_at": "2025-04-01T14:32:10.123Z"
}
```

### POST /appeal

```bash
curl -s -X POST http://localhost:5000/appeal \
  -H "Content-Type: application/json" \
  -d '{
    "content_id": "PASTE-CONTENT-ID-HERE",
    "creator_reasoning": "I wrote this myself from personal experience.",
    "creator_id": "alice"
  }' | python -m json.tool
```

Response:
```json
{
  "content_id": "3f7a2b1e-...",
  "status": "under_review",
  "message": "Your appeal has been received and will be reviewed..."
}
```

### GET /log

```bash
curl -s http://localhost:5000/log | python -m json.tool
```

Returns up to 50 most recent structured entries. Each entry includes
`content_id`, `creator_id`, `timestamp`, `attribution`, `confidence`,
`vocab_score`, `burst_score`, `label`, `status`, and `appeal_reasoning`
(populated after an appeal is filed, null otherwise).

---

## Detection Signals

**Signal 1 — Vocabulary & Formality Analysis** (`vocab_score`):
A composite of Root TTR (lexical diversity), average word length, and
long-word density (words ≥ 7 chars). AI-generated text uses formal,
polysyllabic vocabulary even in short passages.

**Signal 2 — Sentence Burstiness** (`burst_score`):
Coefficient of variation of sentence lengths. AI prose clusters around a
uniform sentence length; human writing mixes very short and very long sentences.

**Confidence scoring**: `0.5 * vocab_score + 0.5 * burst_score`

**Transparency labels**:

| Confidence | Label |
|---|---|
| 0.00 – 0.29 | Likely Human-Written |
| 0.30 – 0.49 | Uncertain — May Be Human or AI |
| 0.50 – 0.69 | Likely AI-Assisted |
| 0.70 – 1.00 | Very Likely AI-Generated |

---

## Rate Limits

The `/submit` endpoint is rate-limited to **10 requests per minute** and
**100 requests per day** per IP address. Exceeding the limit returns HTTP 429.

**Reasoning**: A legitimate writer submitting their own work for provenance
checking does not need more than 10 submissions per minute — that is one piece
every 6 seconds, which is faster than any human can produce original writing.
The per-minute limit prevents scripted flooding. The 100/day cap allows
thorough testing and real creative workflows (a writer finishing a long
document might submit multiple chapters in a day) while blocking bulk
classification of third-party content.

### Rate limit test output

Run 12 rapid requests against a fresh server (which has already had 0 prior
requests in the current minute window):

```
for i in $(seq 1 12); do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:5000/submit \
    -H "Content-Type: application/json" \
    -d '{"text": "Test submission.", "creator_id": "ratelimit-test"}'
done
```

Output (10 accepted, 2 blocked):
```
201
201
201
201
201
201
201
201
201
201
429
429
```

---

## Sample Audit Log

Three structured entries showing different confidence tiers and one appeal:

```json
{
  "entries": [
    {
      "content_id": "8923585a-...",
      "creator_id": "user-alice",
      "timestamp": "2025-04-01T14:32:10Z",
      "attribution": "likely_ai",
      "confidence": 0.6017,
      "vocab_score": 0.685,
      "burst_score": 0.5184,
      "label": "Likely AI-Assisted",
      "status": "under_review",
      "appeal_reasoning": "I wrote this myself. I am a non-native English speaker and my writing may appear formal.",
      "appealed_at": "2025-04-01T14:35:22Z"
    },
    {
      "content_id": "ff2b714b-...",
      "creator_id": "user-bob",
      "timestamp": "2025-04-01T14:33:00Z",
      "attribution": "uncertain",
      "confidence": 0.3874,
      "vocab_score": 0.346,
      "burst_score": 0.4287,
      "label": "Uncertain — May Be Human or AI",
      "status": "classified",
      "appeal_reasoning": null
    },
    {
      "content_id": "034743aa-...",
      "creator_id": "user-carol",
      "timestamp": "2025-04-01T14:33:01Z",
      "attribution": "likely_ai",
      "confidence": 0.5835,
      "vocab_score": 0.667,
      "burst_score": 0.5,
      "label": "Likely AI-Assisted",
      "status": "classified",
      "appeal_reasoning": null
    }
  ],
  "total": 3
}
```

---

## Architecture

See `planning.md` for the full spec, signal formulas, threshold reasoning,
appeals workflow, and edge case analysis.

```
POST /submit → Signal 1 (vocab+formality) + Signal 2 (burstiness)
            → Confidence Score (equal-weight average)
            → Transparency Label
            → Storage + Audit Log
            → Response

POST /appeal → Storage Lookup → Status "under_review"
             → Update global log entry in-place
             → Append event to per-submission timeline
             → Response
```

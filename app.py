import uuid
import threading
from datetime import datetime, timezone

from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from detector import analyze

app = Flask(__name__)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://",
)

_lock = threading.Lock()
_submissions: dict = {}       # content_id → full record
_per_id_events: dict = {}     # content_id → list of timestamped events (for GET /audit/<id>)
_global_log: list = []        # flat list of structured entries (for GET /log)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_event(content_id: str, event: str, detail: dict = None):
    """Append a raw event to the per-submission event list (used by GET /audit/<id>)."""
    entry = {"event": event, "timestamp": _now()}
    if detail:
        entry.update(detail)
    with _lock:
        _per_id_events.setdefault(content_id, []).append(entry)


def _append_log(entry: dict):
    """Append a structured entry to the global audit log (used by GET /log)."""
    with _lock:
        _global_log.append(entry)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/submit", methods=["POST"])
@limiter.limit("30 per minute")
def submit():
    body = request.get_json(silent=True) or {}
    text = body.get("text", "").strip()
    creator_id = body.get("creator_id", "anonymous")

    if not text:
        return jsonify({"error": "text is required"}), 400
    if len(text) > 50_000:
        return jsonify({"error": "text exceeds 50,000 character limit"}), 400

    result = analyze(text)
    content_id = str(uuid.uuid4())
    created_at = _now()

    record = {
        "content_id": content_id,
        "creator_id": creator_id,
        "text_length": len(text),
        "confidence": result["confidence"],
        "attribution": result["attribution"],
        "label": result["label"],
        "signals": {
            "vocabulary_richness": result["vocab_score"],
            "sentence_burstiness": result["burst_score"],
        },
        "status": "classified",
        "created_at": created_at,
    }

    with _lock:
        _submissions[content_id] = record

    # Per-submission event log (for GET /audit/<id>)
    _append_event(content_id, "submitted", {"creator_id": creator_id, "text_length": len(text)})
    _append_event(content_id, "analyzed", {
        "confidence": result["confidence"],
        "attribution": result["attribution"],
        "label": result["label"],
    })

    # Global structured log entry (for GET /log)
    _append_log({
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": created_at,
        "attribution": result["attribution"],
        "confidence": result["confidence"],
        "vocab_score": result["vocab_score"],
        "burst_score": result["burst_score"],
        "status": "classified",
    })

    return jsonify({
        "content_id": content_id,
        "confidence": result["confidence"],
        "attribution": result["attribution"],
        "label": result["label"],
        "signals": record["signals"],
        "status": "classified",
        "created_at": created_at,
    }), 201


@app.route("/status/<content_id>")
def status(content_id):
    with _lock:
        record = _submissions.get(content_id)
    if not record:
        return jsonify({"error": "content not found"}), 404

    return jsonify({
        "content_id": record["content_id"],
        "confidence": record["confidence"],
        "attribution": record["attribution"],
        "label": record["label"],
        "signals": record["signals"],
        "status": record["status"],
        "creator_id": record["creator_id"],
        "created_at": record["created_at"],
    })


@app.route("/appeal/<content_id>", methods=["POST"])
@limiter.limit("10 per minute")
def appeal(content_id):
    with _lock:
        record = _submissions.get(content_id)
    if not record:
        return jsonify({"error": "content not found"}), 404

    body = request.get_json(silent=True) or {}
    reason = body.get("reason", "").strip()
    creator_id = body.get("creator_id", "anonymous")

    if not reason:
        return jsonify({"error": "reason is required"}), 400

    with _lock:
        _submissions[content_id]["status"] = "under_review"
        _submissions[content_id]["appeal_reason"] = reason

    _append_event(content_id, "appeal_submitted", {"creator_id": creator_id, "reason": reason})

    # Update the global log entry status
    _append_log({
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": _now(),
        "event": "appeal_submitted",
        "reason": reason,
        "status": "under_review",
    })

    return jsonify({
        "content_id": content_id,
        "status": "under_review",
        "message": (
            "Your appeal has been received and will be reviewed. "
            "The original classification has been flagged for human review."
        ),
    })


@app.route("/audit/<content_id>")
def audit(content_id):
    with _lock:
        if content_id not in _submissions:
            return jsonify({"error": "content not found"}), 404
        events = list(_per_id_events.get(content_id, []))

    return jsonify({
        "content_id": content_id,
        "events": events,
    })


@app.route("/log")
def log():
    limit = min(int(request.args.get("limit", 50)), 200)
    with _lock:
        entries = list(_global_log[-limit:])
    return jsonify({"entries": entries, "total": len(_global_log)})


if __name__ == "__main__":
    app.run(debug=True)

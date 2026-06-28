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
_submissions: dict = {}
_audit_log: dict = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(submission_id: str, event: str, detail: dict = None):
    entry = {"event": event, "timestamp": _now()}
    if detail:
        entry.update(detail)
    with _lock:
        _audit_log.setdefault(submission_id, []).append(entry)


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
    submission_id = str(uuid.uuid4())
    created_at = _now()

    record = {
        "submission_id": submission_id,
        "creator_id": creator_id,
        "text_length": len(text),
        "confidence": result["confidence"],
        "label": result["label"],
        "signals": {
            "vocabulary_richness": result["vocab_score"],
            "sentence_burstiness": result["burst_score"],
        },
        "status": "reviewed",
        "created_at": created_at,
    }

    with _lock:
        _submissions[submission_id] = record

    _log(submission_id, "submitted", {"creator_id": creator_id, "text_length": len(text)})
    _log(submission_id, "analyzed", {"confidence": result["confidence"], "label": result["label"]})

    return jsonify({
        "submission_id": submission_id,
        "confidence": result["confidence"],
        "label": result["label"],
        "signals": record["signals"],
        "status": "reviewed",
        "created_at": created_at,
    }), 201


@app.route("/status/<submission_id>")
def status(submission_id):
    with _lock:
        record = _submissions.get(submission_id)
    if not record:
        return jsonify({"error": "submission not found"}), 404

    return jsonify({
        "submission_id": record["submission_id"],
        "confidence": record["confidence"],
        "label": record["label"],
        "signals": record["signals"],
        "status": record["status"],
        "creator_id": record["creator_id"],
        "created_at": record["created_at"],
    })


@app.route("/appeal/<submission_id>", methods=["POST"])
@limiter.limit("10 per minute")
def appeal(submission_id):
    with _lock:
        record = _submissions.get(submission_id)
    if not record:
        return jsonify({"error": "submission not found"}), 404

    body = request.get_json(silent=True) or {}
    reason = body.get("reason", "").strip()
    creator_id = body.get("creator_id", "anonymous")

    if not reason:
        return jsonify({"error": "reason is required"}), 400

    with _lock:
        _submissions[submission_id]["status"] = "under_review"
        _submissions[submission_id]["appeal_reason"] = reason

    _log(submission_id, "appeal_submitted", {"creator_id": creator_id, "reason": reason})

    return jsonify({
        "submission_id": submission_id,
        "status": "under_review",
        "message": (
            "Your appeal has been received and will be reviewed. "
            "The original classification has been flagged for human review."
        ),
    })


@app.route("/audit/<submission_id>")
def audit(submission_id):
    with _lock:
        if submission_id not in _submissions:
            return jsonify({"error": "submission not found"}), 404
        events = list(_audit_log.get(submission_id, []))

    return jsonify({
        "submission_id": submission_id,
        "events": events,
    })


if __name__ == "__main__":
    app.run(debug=True)

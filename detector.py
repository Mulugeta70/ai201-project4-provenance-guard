import re
import math
import statistics
from typing import TypedDict


class DetectionResult(TypedDict):
    vocab_score: float
    burst_score: float
    confidence: float
    attribution: str
    label: str


def _vocabulary_ai_score(text: str) -> float:
    """
    Signal 1: Vocabulary & Formality Analysis (composite of 3 sub-metrics).

    Sub-metric 1 — Root TTR: measures lexical diversity relative to length.
      Low diversity (repeating the same words) → AI-like.
    Sub-metric 2 — Average word length: formal/academic writing favors longer
      words ("implement", "implications", "transformative") while casual human
      writing uses shorter ones ("ok", "fine", "bad"). AI tends formal.
    Sub-metric 3 — Long-word density: fraction of words ≥ 7 characters.
      Academic and AI prose pack in polysyllabic vocabulary; colloquial human
      writing avoids it.

    All three sub-scores are in [0, 1] (higher = more AI-like) and averaged
    with equal weight.
    """
    words = re.findall(r'\b[a-zA-Z]+\b', text.lower())
    if len(words) < 10:
        return 0.5  # insufficient data — neutral

    n = len(words)

    # Sub-metric 1: Root TTR (low diversity → AI-like)
    ttr = len(set(words)) / n
    rttr = ttr * math.sqrt(n)
    rttr_score = max(0.0, min(1.0, 1.0 / (1.0 + rttr / 4.0)))

    # Sub-metric 2: Average word length (longer → more formal → AI-like)
    # Mapping: avg_len 3 → 0.0 (very short); 5.5 → 0.5; 8+ → 1.0
    avg_len = sum(len(w) for w in words) / n
    len_score = max(0.0, min(1.0, (avg_len - 3.0) / 5.0))

    # Sub-metric 3: Long-word density (words ≥ 7 chars; higher → more AI-like)
    # Mapping: density 0% → 0.0; 40% → 1.0
    long_density = sum(1 for w in words if len(w) >= 7) / n
    density_score = min(1.0, long_density * 2.5)

    return round((rttr_score + len_score + density_score) / 3.0, 4)


def _burstiness_ai_score(text: str) -> float:
    """
    Signal 2: Sentence Length Burstiness.

    Measures the coefficient of variation (std / mean) of sentence lengths
    in words. Low CoV means uniform sentence lengths → AI-like. High CoV
    means varied rhythm (short punches mixed with long clauses) → human-like.

    Returns a float in [0, 1] (higher = more AI-like).
    """
    sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
    if len(sentences) < 3:
        return 0.5  # insufficient data — neutral
    lengths = [
        len(re.findall(r'\b\w+\b', s))
        for s in sentences
        if re.findall(r'\b\w+\b', s)
    ]
    if len(lengths) < 3:
        return 0.5
    mean = statistics.mean(lengths)
    if mean == 0:
        return 0.5
    cov = statistics.stdev(lengths) / mean
    # cov ≈ 0.10 (very uniform) → ~0.83 AI
    # cov ≈ 0.50 (moderate)    → ~0.50 AI
    # cov ≈ 1.00 (very varied) → ~0.33 AI
    return max(0.0, min(1.0, 1.0 / (1.0 + cov * 2.0)))


def _attribution(confidence: float) -> str:
    """Machine-readable classification used in audit log and API responses."""
    if confidence < 0.30:
        return "likely_human"
    elif confidence < 0.50:
        return "uncertain"
    else:
        return "likely_ai"


def _label(confidence: float) -> str:
    """Human-readable transparency label shown to creators."""
    if confidence < 0.30:
        return "Likely Human-Written"
    elif confidence < 0.50:
        return "Uncertain — May Be Human or AI"
    elif confidence < 0.70:
        return "Likely AI-Assisted"
    else:
        return "Very Likely AI-Generated"


def analyze(text: str) -> DetectionResult:
    vocab_score = _vocabulary_ai_score(text)
    burst_score = _burstiness_ai_score(text)
    confidence = round(0.5 * vocab_score + 0.5 * burst_score, 4)
    return DetectionResult(
        vocab_score=round(vocab_score, 4),
        burst_score=round(burst_score, 4),
        confidence=confidence,
        attribution=_attribution(confidence),
        label=_label(confidence),
    )

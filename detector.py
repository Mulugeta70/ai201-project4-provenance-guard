import re
import math
import statistics
from typing import TypedDict


class DetectionResult(TypedDict):
    vocab_score: float
    burst_score: float
    confidence: float
    label: str


def _vocabulary_ai_score(text: str) -> float:
    """
    Measures vocabulary richness via Root TTR.
    Low variety (repetitive word choice) → higher AI score.
    Returns a float in [0, 1].
    """
    words = re.findall(r'\b[a-zA-Z]+\b', text.lower())
    if len(words) < 10:
        return 0.5  # insufficient data — neutral
    n = len(words)
    ttr = len(set(words)) / n
    rttr = ttr * math.sqrt(n)
    # High RTTR → human-like. Map to AI score via inverse relationship.
    # rttr ≈ 3 → ~0.75 AI; rttr ≈ 8 → ~0.38 AI; rttr ≈ 15 → ~0.22 AI
    return max(0.0, min(1.0, 1.0 / (1.0 + rttr / 4.0)))


def _burstiness_ai_score(text: str) -> float:
    """
    Measures sentence length variance via coefficient of variation.
    Uniform sentence lengths (low CoV) → higher AI score.
    Returns a float in [0, 1].
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
    # High CoV → human-like. Map to AI score via inverse relationship.
    # cov ≈ 0.1 → ~0.83 AI; cov ≈ 0.5 → ~0.5 AI; cov ≈ 1.0 → ~0.33 AI
    return max(0.0, min(1.0, 1.0 / (1.0 + cov * 2.0)))


def _label(confidence: float) -> str:
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
        label=_label(confidence),
    )

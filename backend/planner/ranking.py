"""Choose the recommended route.

Sort ascending, first difference wins:

1. No Travel miles. No Travel is worse than Severe, so it is its own bucket
   and outranks every Severe-mile comparison. A route with any No Travel
   miles loses to a route whose worst mile is Severe.
2. Severe miles.
3. High miles.
4. Mileage-weighted average risk. Scores are Low 0, Moderate 1, High 2,
   Severe 3, No Travel 4. Average = sum(segment miles * score) / total miles.
5. Travel time in seconds.
6. Original route index, so a complete tie prefers the earlier OSRM option.

Moderate miles affect the order only through the average. Each mile is in
exactly one bucket. No Travel miles are not also counted as Severe.
"""

from __future__ import annotations

from dataclasses import dataclass

from planner.risk import LEVELS, SCORE


@dataclass(frozen=True)
class SegmentRisk:
    level: str
    miles: float


@dataclass(frozen=True)
class RouteScore:
    no_travel_miles: float
    severe_miles: float
    high_miles: float
    moderate_miles: float
    low_miles: float
    average_risk: float
    duration_seconds: float


def score_segments(segments: list[SegmentRisk], duration_seconds: float) -> RouteScore:
    """Sum risk miles. Zero-length segments (the origin) are ignored."""
    buckets = {level: 0.0 for level in LEVELS}
    weighted = 0.0
    total = 0.0
    for segment in segments:
        miles = float(segment.miles)
        if miles <= 0:
            continue
        buckets[segment.level] += miles
        weighted += miles * SCORE[segment.level]
        total += miles
    average = weighted / total if total else 0.0
    return RouteScore(
        no_travel_miles=buckets["no_travel"],
        severe_miles=buckets["severe"],
        high_miles=buckets["high"],
        moderate_miles=buckets["moderate"],
        low_miles=buckets["low"],
        average_risk=average,
        duration_seconds=float(duration_seconds),
    )


def rank_key(score: RouteScore, index: int) -> tuple:
    """Comparison key. Smaller is safer, then faster, then earlier."""
    return (
        round(score.no_travel_miles, 2),
        round(score.severe_miles, 2),
        round(score.high_miles, 2),
        round(score.average_risk, 6),
        round(score.duration_seconds, 3),
        index,
    )


def best_index(scores: list[RouteScore]) -> int:
    if not scores:
        raise ValueError("At least one route score is required.")
    return min(range(len(scores)), key=lambda index: rank_key(scores[index], index))


def rank_order(scores: list[RouteScore]) -> list[int]:
    """Route indexes from best to worst."""
    return sorted(range(len(scores)), key=lambda index: rank_key(scores[index], index))

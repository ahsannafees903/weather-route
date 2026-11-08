"""Pure weather-and-load risk classification.

Boundary interpretation
-----------------------
The published table writes ranges that meet or overlap. This module makes
those edges explicit so every threshold test has one answer.

Wind is printed as integer bands (25–34, 35–44, 45–54). Those are treated as
contiguous half-open intervals that start at the first number of each band.
A reading that lands on 25, 35, 45, or 55 belongs to the higher band. There
is no gap between 34 and 35: 34.9 mph is still Moderate because it is below 35.

    wind < 25            Low
    25 <= wind < 35      Moderate
    35 <= wind < 45      High
    45 <= wind < 55      Severe
    wind >= 55           No Travel

Rain and snow are printed with shared endpoints (rain 0.25 and 0.50, snow
1.0 and 2.0). When a reading sits in two bands, the worse band wins. The top
of Severe stays Severe, because No Travel is strictly greater than that end:

    rain < 0.10                 Low
    0.10 <= rain < 0.25         Moderate
    0.25 <= rain < 0.50         High       (0.25 is also in Moderate; worse wins)
    0.50 <= rain <= 1.00        Severe     (0.50 is also in High; worse wins)
    rain > 1.00                 No Travel  (1.00 itself stays Severe)

    snow < 0.5                  Low
    0.5 <= snow < 1.0           Moderate
    1.0 <= snow < 2.0           High
    2.0 <= snow <= 3.0          Severe
    snow > 3.0                  No Travel

Load rules are applied to the wind speed after the wind band is chosen. They
only raise wind risk; they never lower it and they do not reclassify rain or
snow.

    wind >= 55                         No Travel for any load, including an empty truck
    45 <= wind < 55 and load > 30000   No Travel
    35 <= wind < 45 and load > 40000   Severe

Exactly 30,000 lb does not trip the 45–54 rule. Exactly 40,000 lb does not
trip the 35–44 rule. The inequalities are strict, matching the brief.

The checkpoint level is the worst of wind-after-load, rain, and snow.
No Travel is worse than Severe. Ranking keeps those miles in separate
buckets and sorts No Travel miles first (see ``ranking.py``).

Negative readings are treated as zero. Missing readings should be coerced
to zero by the caller before they reach this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

LOW = "low"
MODERATE = "moderate"
HIGH = "high"
SEVERE = "severe"
NO_TRAVEL = "no_travel"

LEVELS = (LOW, MODERATE, HIGH, SEVERE, NO_TRAVEL)
SCORE = {level: index for index, level in enumerate(LEVELS)}

_LABEL = {
    LOW: "Low",
    MODERATE: "Moderate",
    HIGH: "High",
    SEVERE: "Severe",
    NO_TRAVEL: "No Travel",
}


def _decimal(value: float | int | str | Decimal) -> Decimal:
    if isinstance(value, Decimal):
        number = value
    else:
        number = Decimal(str(value))
    if number < 0:
        return Decimal("0")
    return number


def classify_wind(wind_mph: float) -> str:
    """Return the wind band before load rules are applied."""
    wind = _decimal(wind_mph)
    if wind >= 55:
        return NO_TRAVEL
    if wind >= 45:
        return SEVERE
    if wind >= 35:
        return HIGH
    if wind >= 25:
        return MODERATE
    return LOW


def classify_rain(rain_in_hr: float) -> str:
    """Return the rain band. Shared endpoints take the worse band."""
    rain = _decimal(rain_in_hr)
    if rain > 1:
        return NO_TRAVEL
    if rain >= Decimal("0.50"):
        return SEVERE
    if rain >= Decimal("0.25"):
        return HIGH
    if rain >= Decimal("0.10"):
        return MODERATE
    return LOW


def classify_snow(snow_in_hr: float) -> str:
    """Return the snow band. Shared endpoints take the worse band."""
    snow = _decimal(snow_in_hr)
    if snow > 3:
        return NO_TRAVEL
    if snow >= 2:
        return SEVERE
    if snow >= 1:
        return HIGH
    if snow >= Decimal("0.5"):
        return MODERATE
    return LOW


def apply_load(wind_mph: float, load_lb: float, wind_level: str) -> str:
    """Raise wind risk when the load rules say so. Never lowers it."""
    wind = _decimal(wind_mph)
    load = _decimal(load_lb)
    if wind >= 55:
        return NO_TRAVEL
    if wind >= 45 and load > 30000:
        return NO_TRAVEL
    if wind >= 35 and load > 40000:
        return SEVERE
    return wind_level


def worse(left: str, right: str) -> str:
    """Return the higher of two risk levels. No Travel outranks Severe."""
    return left if SCORE[left] >= SCORE[right] else right


@dataclass(frozen=True)
class RiskAssessment:
    level: str
    score: int
    wind_level: str
    rain_level: str
    snow_level: str
    wind_after_load: str
    reason: str


def _reason(
    level: str,
    wind_level: str,
    wind_after_load: str,
    rain_level: str,
    snow_level: str,
) -> str:
    sources: list[str] = []
    if wind_after_load == level:
        sources.append("wind + load" if wind_after_load != wind_level else "wind")
    if rain_level == level:
        sources.append("rain")
    if snow_level == level:
        sources.append("snow")
    if not sources:
        sources.append("wind")
    return f"{_LABEL[level]} from {', '.join(sources)}"


def classify(
    wind_mph: float,
    rain_in_hr: float,
    snow_in_hr: float,
    load_lb: float,
) -> RiskAssessment:
    """Classify one checkpoint. Load rules apply only to wind."""
    wind_level = classify_wind(wind_mph)
    rain_level = classify_rain(rain_in_hr)
    snow_level = classify_snow(snow_in_hr)
    wind_after_load = apply_load(wind_mph, load_lb, wind_level)
    level = worse(wind_after_load, worse(rain_level, snow_level))
    return RiskAssessment(
        level=level,
        score=SCORE[level],
        wind_level=wind_level,
        rain_level=rain_level,
        snow_level=snow_level,
        wind_after_load=wind_after_load,
        reason=_reason(level, wind_level, wind_after_load, rain_level, snow_level),
    )

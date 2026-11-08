"""Build a route plan from a JSON request body.

The view stays thin. This module validates input, calls geocoding, routing,
and weather, then classifies every checkpoint and ranks the routes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from planner.checkpoints import build_checkpoints
from planner.exceptions import BadInput, NoRoute, UpstreamFailure
from planner.geocode import Place, geocode_place
from planner.geo import haversine, point_at_miles, polyline_miles, simplify
from planner.osrm import RawRoute, fetch_route_options
from planner.ranking import SegmentRisk, best_index, rank_order, score_segments
from planner.risk import classify
from planner.timezones import resolve_departure
from planner.weather import fetch_forecasts, round_key

ASSUMPTIONS = [
    "ETAs assume a constant speed along each route, using the routing engine's total time.",
    "Each stretch of road uses the weather at the checkpoint that ends it. The origin sample is shown and adds no miles.",
    "Wind bands start at 25, 35, 45, and 55 mph. Shared rain and snow endpoints take the worse category. 1.00 in/hr of rain and 3.0 in/hr of snow stay Severe.",
    "Load rules only raise wind risk: above 30,000 lb makes 45–54 mph No Travel, and above 40,000 lb makes 35–44 mph Severe.",
    "No Travel miles outrank Severe miles. Then fewest High miles, then lowest mileage-weighted average risk, then shortest time.",
]

_ALLOWED_INTERVALS = {10, 25, 50}
_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def current_time() -> datetime:
    return datetime.now(timezone.utc)


def _place_name(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BadInput(f"{field} is required.")
    text = " ".join(value.strip().split())
    if len(text) < 2:
        raise BadInput(f"{field} is too short.")
    if len(text) > 200:
        raise BadInput(f"{field} is too long.")
    return text


def _load_weight(value) -> float:
    if isinstance(value, bool) or value is None or isinstance(value, str) and not value.strip():
        raise BadInput("load_weight_lb is required and must be a number of pounds from 0 to 500000.")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise BadInput("load_weight_lb is required and must be a number of pounds from 0 to 500000.") from None
    if number != number or number in {float("inf"), float("-inf")}:
        raise BadInput("load_weight_lb is required and must be a number of pounds from 0 to 500000.")
    if number < 0 or number > 500000:
        raise BadInput("load_weight_lb must be a number of pounds from 0 to 500000.")
    return number


def _interval(value) -> int:
    if value is None:
        return 25
    if isinstance(value, bool):
        raise BadInput("interval_miles must be 10, 25, or 50.")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise BadInput("interval_miles must be 10, 25, or 50.") from None
    if number not in _ALLOWED_INTERVALS:
        raise BadInput("interval_miles must be 10, 25, or 50.")
    return int(number)


def _parse_departure(value) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise BadInput("departure is required and must be an ISO 8601 date and time.")
    raw = value.strip()
    text = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise BadInput(
            "departure must be an ISO 8601 date and time, for example 2026-11-06T08:00."
        ) from None
    if "T" not in raw and " " not in raw:
        raise BadInput("departure must include a time, for example 2026-11-06T08:00.")
    return parsed


def _check_window(departure_utc: datetime, now: datetime) -> None:
    if departure_utc < now - timedelta(hours=6):
        raise BadInput(
            "departure is too far in the past for the hourly forecast. "
            "Choose a time within the last 6 hours or later."
        )
    if departure_utc > now + timedelta(days=14):
        raise BadInput(
            "departure is outside the forecast window. Choose a time within the next 14 days."
        )


def _heatmap_points(routes: list[RawRoute], step: float = 15.0, min_sep: float = 8.0):
    chosen = []
    for route in routes:
        try:
            points, cumulative = polyline_miles(route.geometry)
        except ValueError:
            continue
        mark = 0.0
        while mark <= cumulative[-1] + 1e-6:
            point = point_at_miles(points, cumulative, min(mark, cumulative[-1]))
            if all(haversine(point, existing) >= min_sep for existing in chosen):
                chosen.append(point)
            if mark >= cumulative[-1]:
                break
            mark += step
    return chosen


def _place_payload(place: Place) -> dict:
    return {
        "query": place.query,
        "label": place.label,
        "lat": round(place.lat, 5),
        "lon": round(place.lon, 5),
        "timezone": place.timezone,
    }


def _iso_z(value: datetime) -> str:
    stamp = value.astimezone(timezone.utc)
    if stamp.microsecond >= 500_000:
        stamp += timedelta(seconds=1)
    return stamp.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _duration_text(seconds: float) -> str:
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes = remainder // 60
    if hours <= 0:
        return f"{minutes} min"
    return f"{hours} h {minutes:02d} min"


def build_plan(payload: dict, *, now: datetime | None = None) -> dict:
    """Validate ``payload`` and return the JSON-ready plan."""
    if not isinstance(payload, dict):
        raise BadInput("Request body must be a JSON object.")

    origin_query = _place_name(payload.get("origin"), "origin")
    destination_query = _place_name(payload.get("destination"), "destination")
    load = _load_weight(payload.get("load_weight_lb"))
    interval = _interval(payload.get("interval_miles", 25))
    parsed_departure = _parse_departure(payload.get("departure"))

    clock = now or current_time()
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    clock = clock.astimezone(timezone.utc)

    if parsed_departure.tzinfo is not None:
        _check_window(parsed_departure.astimezone(timezone.utc), clock)

    origin = geocode_place(origin_query)
    destination = geocode_place(destination_query)
    if haversine((origin.lat, origin.lon), (destination.lat, destination.lon)) < 1:
        raise BadInput("Origin and destination resolve to the same place.")

    resolved = resolve_departure(parsed_departure, origin.timezone, origin.lon)
    if parsed_departure.tzinfo is None:
        _check_window(resolved.utc, clock)

    routes, notes = fetch_route_options(
        (origin.lat, origin.lon),
        (destination.lat, destination.lon),
    )
    if not routes:
        raise NoRoute("The routing service did not return a road route between those points.")

    longest = max(route.duration_seconds for route in routes)
    window_start = resolved.utc - timedelta(hours=2)
    window_end = resolved.utc + timedelta(hours=max(48, longest / 3600) + 3)

    checkpoint_sets = []
    sample_points = []
    for route in routes:
        try:
            slots = build_checkpoints(
                route.geometry,
                interval,
                route.duration_seconds,
                resolved.utc,
                route.distance_miles,
            )
        except ValueError as exc:
            raise NoRoute("The routing service returned a route with no drivable length.") from exc
        checkpoint_sets.append(slots)
        sample_points.extend((slot.lat, slot.lon) for slot in slots)

    heat_points = _heatmap_points(routes)
    sample_points.extend(heat_points)
    try:
        forecasts = fetch_forecasts(sample_points, window_start, window_end)
    except UpstreamFailure:
        raise

    clamped_any = False
    scored = []
    classified_sets = []
    for route, slots in zip(routes, checkpoint_sets):
        classified = []
        for slot in slots:
            series = forecasts.get(round_key(slot.lat, slot.lon))
            if series is None:
                raise UpstreamFailure("The weather service failed. Try again in a moment.")
            wind, rain, snow, clamped = series.at(slot.eta)
            clamped_any = clamped_any or clamped
            assessment = classify(wind, rain, snow, load)
            classified.append((slot, wind, rain, snow, assessment))
        classified_sets.append(classified)
        scored.append(
            score_segments(
                [SegmentRisk(item[4].level, item[0].segment_miles) for item in classified],
                route.duration_seconds,
            )
        )

    if clamped_any:
        notes.append(
            "Some checkpoint times fell outside the returned forecast and were matched "
            "to the nearest available hour."
        )

    winner = best_index(scored)
    order = rank_order(scored)
    rank_of = {index: rank for rank, index in enumerate(order, start=1)}

    route_payloads = []
    for index, (route, classified, score) in enumerate(zip(routes, classified_sets, scored)):
        route_payloads.append(
            {
                "id": _LETTERS[index],
                "name": f"Route {_LETTERS[index]}",
                "source": route.source,
                "via": (
                    {"lat": round(route.via[0], 5), "lon": round(route.via[1], 5)}
                    if route.via
                    else None
                ),
                "summary": route.summary,
                "distance_miles": round(route.distance_miles, 1),
                "duration_seconds": round(route.duration_seconds, 1),
                "duration_text": _duration_text(route.duration_seconds),
                "geometry": [
                    [round(lat, 5), round(lon, 5)] for lat, lon in simplify(route.geometry)
                ],
                "miles": {
                    "no_travel": round(score.no_travel_miles, 1),
                    "severe": round(score.severe_miles, 1),
                    "high": round(score.high_miles, 1),
                    "moderate": round(score.moderate_miles, 1),
                    "low": round(score.low_miles, 1),
                },
                "average_risk": round(score.average_risk, 3),
                "recommended": index == winner,
                "rank": rank_of[index],
                "checkpoints": [
                    {
                        "mile": round(slot.mile, 2),
                        "lat": round(slot.lat, 5),
                        "lon": round(slot.lon, 5),
                        "eta": _iso_z(slot.eta),
                        "eta_local": slot.eta.astimezone(resolved.local.tzinfo).replace(microsecond=0).isoformat(),
                        "wind_mph": round(wind, 1),
                        "rain_in_hr": round(rain, 3),
                        "snow_in_hr": round(snow, 3),
                        "level": assessment.level,
                        "segment_miles": round(slot.segment_miles, 2),
                        "reason": assessment.reason,
                    }
                    for slot, wind, rain, snow, assessment in classified
                ],
            }
        )

    heatmap = []
    for lat, lon in heat_points:
        series = forecasts.get(round_key(lat, lon))
        if series is None:
            continue
        values = []
        for hour in range(49):
            moment = resolved.utc + timedelta(hours=hour)
            wind, rain, snow, _clamped = series.at(moment)
            values.append(classify(wind, rain, snow, load).score)
        heatmap.append(
            {"lat": round(lat, 5), "lon": round(lon, 5), "values": values}
        )

    return {
        "origin": _place_payload(origin),
        "destination": _place_payload(destination),
        "departure": {
            "local": resolved.local.isoformat(),
            "utc": resolved.utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "timezone": resolved.timezone_name,
        },
        "load_weight_lb": load,
        "interval_miles": interval,
        "recommended_route_id": _LETTERS[winner],
        "notes": notes,
        "assumptions": ASSUMPTIONS,
        "routes": route_payloads,
        "heatmap": {
            "hour_count": 49,
            "points": heatmap,
        },
    }

"""Driving routes from the public OSRM server.

``alternatives=2`` asks for up to two alternates plus the primary route.
The public server often returns only one or two. When that happens, this
module builds extra options by routing through a via-waypoint offset to the
side of the fastest route (both directions, then a larger offset, then
other positions along the line). A candidate is kept only when a meaningful
share of it stays away from the routes already chosen, and when it is not
an unreasonable detour.

The detour cap is 1.85x the fastest accepted duration, or 1.9x the shortest
distance (so a shorter mountain road with a lower speed limit can still
qualify). If that still leaves fewer than three routes, the cap relaxes to
2.4x duration or 2.6x distance. At most six via requests are made.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

from planner import http_client
from planner.exceptions import NoRoute, UpstreamFailure
from planner.geo import (
    METERS_PER_MILE,
    LatLon,
    destination_point,
    haversine,
    local_bearing,
    point_at_miles,
    polyline_miles,
)

logger = logging.getLogger(__name__)

_CACHE_SECONDS = 60 * 60


@dataclass
class RawRoute:
    distance_miles: float
    duration_seconds: float
    geometry: list[LatLon]
    summary: str
    source: str
    via: LatLon | None = None


def road_summary(legs: list[dict] | None) -> str:
    """Name the route from the longest step refs, for example ``I 80 · I 25``."""
    totals: dict[str, float] = {}
    for leg in legs or []:
        for step in leg.get("steps") or []:
            label = str(step.get("ref") or step.get("name") or "").strip()
            if not label or label.lower() == "unnamed road":
                continue
            totals[label] = totals.get(label, 0.0) + float(step.get("distance") or 0)
    if not totals:
        return "Driving route"
    ranked = sorted(totals.items(), key=lambda item: item[1], reverse=True)
    seen: list[str] = []
    for label, _distance in ranked:
        short = label.split(";")[0].strip()
        if short and short not in seen:
            seen.append(short)
        if len(seen) == 3:
            break
    return " · ".join(seen) if seen else "Driving route"


def parse_osrm(payload: dict, source: str = "osrm") -> list[RawRoute]:
    """Turn an OSRM route response into raw routes. ``NoRoute`` yields []."""
    if not isinstance(payload, dict):
        raise UpstreamFailure("The routing service failed. Try again in a moment.")
    code = payload.get("code")
    if code == "NoRoute":
        return []
    if code != "Ok":
        logger.warning("OSRM code %s: %s", code, payload.get("message"))
        raise UpstreamFailure("The routing service failed. Try again in a moment.")

    routes: list[RawRoute] = []
    for item in payload.get("routes") or []:
        geometry = item.get("geometry") or {}
        coordinates = geometry.get("coordinates") or []
        latlon: list[LatLon] = []
        for pair in coordinates:
            if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                latlon.append((float(pair[1]), float(pair[0])))
        distance_m = float(item.get("distance") or 0)
        duration_s = float(item.get("duration") or 0)
        if len(latlon) < 2 or distance_m <= 1 or duration_s < 0:
            continue
        routes.append(
            RawRoute(
                distance_miles=distance_m / METERS_PER_MILE,
                duration_seconds=duration_s,
                geometry=latlon,
                summary=road_summary(item.get("legs")),
                source=source,
            )
        )
    return routes


def _cache_key(latlons: list[LatLon], alternatives: int) -> str:
    path = ";".join(f"{lon:.4f},{lat:.4f}" for lat, lon in latlons)
    digest = hashlib.sha256(f"{path}:{alternatives}".encode()).hexdigest()
    return f"osrm1-{digest}"


def _request(latlons: list[LatLon], alternatives: int) -> list[RawRoute]:
    path = ";".join(f"{lon:.5f},{lat:.5f}" for lat, lon in latlons)
    url = f"{settings.OSRM_URL.rstrip('/')}/route/v1/driving/{path}"
    params = {
        "overview": "full",
        "geometries": "geojson",
        "steps": "true",
        "alternatives": str(alternatives) if alternatives else "false",
    }
    key = _cache_key(latlons, alternatives)
    cached = cache.get(key)
    if cached is not None:
        return parse_osrm(cached, source="osrm")
    payload = http_client.get_json(url, params=params, service="routing", timeout=30)
    routes = parse_osrm(payload, source="osrm")
    if isinstance(payload, dict) and payload.get("code") == "Ok" and routes:
        cache.set(key, payload, _CACHE_SECONDS)
    return routes


def _samples(geometry: list[LatLon], step_miles: float) -> list[LatLon]:
    points, cumulative = polyline_miles(geometry)
    samples = []
    mark = 0.0
    while mark < cumulative[-1]:
        samples.append(point_at_miles(points, cumulative, mark))
        mark += step_miles
    samples.append(points[-1])
    return samples


def _distinct(candidate: RawRoute, others: list[RawRoute]) -> bool:
    """True when at least ~28% of the candidate is 15 miles or more off the others."""
    if not others:
        return True
    try:
        left = _samples(candidate.geometry, 20)
    except ValueError:
        return False
    pools: list[list[LatLon]] = []
    for other in others:
        try:
            pools.append(_samples(other.geometry, 10))
        except ValueError:
            continue
    if not pools or not left:
        return False
    far = 0
    distance_sum = 0.0
    for point in left:
        nearest = min(haversine(point, other) for pool in pools for other in pool)
        distance_sum += nearest
        if nearest >= 15:
            far += 1
    fraction = far / len(left)
    mean = distance_sum / len(left)
    return fraction >= 0.28 or mean >= 22


def _acceptable(candidate: RawRoute, baselines: list[RawRoute], *, relaxed: bool) -> bool:
    if not baselines:
        return True
    min_duration = min(route.duration_seconds for route in baselines)
    min_distance = min(route.distance_miles for route in baselines)
    duration_cap = 2.4 if relaxed else 1.85
    distance_cap = 2.6 if relaxed else 1.9
    return (
        candidate.duration_seconds <= duration_cap * min_duration
        or candidate.distance_miles <= distance_cap * min_distance
    )


def propose_vias(origin: LatLon, destination: LatLon, geometry: list[LatLon]) -> list[LatLon]:
    """Side-of-route via points, best first. Callers stop once they have enough."""
    points, cumulative = polyline_miles(geometry)
    length = cumulative[-1]
    straight = max(haversine(origin, destination), 1.0)
    medium = max(40.0, min(160.0, straight * 0.25))
    large = max(70.0, min(220.0, straight * 0.42))
    vias: list[LatLon] = []
    for fraction in (0.50, 0.35, 0.65):
        for offset in (medium, large):
            anchor_mile = length * fraction
            anchor = point_at_miles(points, cumulative, anchor_mile)
            direction = local_bearing(points, cumulative, anchor_mile)
            for turn in (90.0, -90.0):
                vias.append(destination_point(anchor, (direction + turn) % 360.0, offset))
    return vias


def _dedupe(routes: list[RawRoute]) -> list[RawRoute]:
    kept: list[RawRoute] = []
    for route in routes:
        if _distinct(route, kept):
            kept.append(route)
    return kept


def fetch_route_options(origin: LatLon, destination: LatLon) -> tuple[list[RawRoute], list[str]]:
    """Return up to three distinct driving routes and human-readable notes."""
    notes: list[str] = []
    try:
        initial = _request([origin, destination], alternatives=2)
    except UpstreamFailure:
        raise
    except Exception:
        logger.exception("routing failed")
        raise UpstreamFailure("The routing service failed. Try again in a moment.") from None

    chosen = _dedupe(initial)
    if not chosen:
        raise NoRoute("The routing service did not return a road route between those points.")
    if len(chosen) >= 3:
        return chosen[:3], notes

    skipped: list[RawRoute] = []
    attempts = 0
    try:
        vias = propose_vias(origin, destination, chosen[0].geometry)
    except ValueError:
        vias = []

    for via in vias:
        if len(chosen) >= 3 or attempts >= 6:
            break
        attempts += 1
        try:
            batch = _request([origin, via, destination], alternatives=0)
        except UpstreamFailure:
            logger.warning("via-route request failed; trying the next offset")
            continue
        except Exception:
            logger.exception("via-route request errored")
            continue
        if not batch:
            continue
        candidate = batch[0]
        candidate.source = "via"
        candidate.via = via
        if not _distinct(candidate, chosen):
            continue
        if _acceptable(candidate, chosen, relaxed=False):
            chosen.append(candidate)
        else:
            skipped.append(candidate)

    if len(chosen) < 3:
        for candidate in skipped:
            if len(chosen) >= 3:
                break
            if _acceptable(candidate, chosen, relaxed=True) and _distinct(candidate, chosen):
                chosen.append(candidate)

    if any(route.source == "via" for route in chosen):
        notes.append(
            "OSRM returned fewer than 3 alternatives. Additional routes were built by "
            "routing through an offset via-waypoint beside the fastest road, then keeping "
            "only corridors that stay on a different path."
        )
    if len(chosen) < 3:
        notes.append(
            f"Only {len(chosen)} distinct drivable route(s) could be built for this pair."
        )
    return chosen[:3], notes

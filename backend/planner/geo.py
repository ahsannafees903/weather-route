"""Polyline math in statute miles.

Distances use the haversine formula on a spherical Earth. Points along a
short OSRM segment are interpolated linearly in latitude and longitude,
which is accurate for the sub-mile segments a full driving geometry uses.
Routes that cross the antimeridian are not supported.
"""

from __future__ import annotations

import math

EARTH_RADIUS_MILES = 3958.7613
METERS_PER_MILE = 1609.344

LatLon = tuple[float, float]


def haversine(a: LatLon, b: LatLon) -> float:
    """Great-circle distance in miles."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    half = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(min(1.0, math.sqrt(half)))


def bearing(a: LatLon, b: LatLon) -> float:
    """Initial bearing from ``a`` to ``b`` in degrees, 0 = north, 90 = east."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def destination_point(start: LatLon, bearing_deg: float, miles: float) -> LatLon:
    """Point reached by traveling ``miles`` from ``start`` on a constant bearing."""
    lat1 = math.radians(start[0])
    lon1 = math.radians(start[1])
    brg = math.radians(bearing_deg)
    ang = miles / EARTH_RADIUS_MILES
    lat2 = math.asin(
        math.sin(lat1) * math.cos(ang) + math.cos(lat1) * math.sin(ang) * math.cos(brg)
    )
    lon2 = lon1 + math.atan2(
        math.sin(brg) * math.sin(ang) * math.cos(lat1),
        math.cos(ang) - math.sin(lat1) * math.sin(lat2),
    )
    lon_deg = (math.degrees(lon2) + 540.0) % 360.0 - 180.0
    return (math.degrees(lat2), lon_deg)


def polyline_miles(points: list[LatLon]) -> tuple[list[LatLon], list[float]]:
    """Drop duplicate vertices and return cumulative miles along the line."""
    if len(points) < 2:
        raise ValueError("A route geometry needs at least two points.")
    cleaned = [points[0]]
    cumulative = [0.0]
    for point in points[1:]:
        step = haversine(cleaned[-1], point)
        if step < 1e-6:
            continue
        cleaned.append(point)
        cumulative.append(cumulative[-1] + step)
    if len(cleaned) < 2 or cumulative[-1] <= 0:
        raise ValueError("Route geometry has no length.")
    return cleaned, cumulative


def point_at_miles(points: list[LatLon], cumulative: list[float], target: float) -> LatLon:
    """Interpolate the coordinate at ``target`` miles along the polyline."""
    if target <= 0:
        return points[0]
    if target >= cumulative[-1]:
        return points[-1]
    lo = 1
    hi = len(cumulative) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if cumulative[mid] < target:
            lo = mid + 1
        else:
            hi = mid
    span = cumulative[lo] - cumulative[lo - 1]
    fraction = 0.0 if span == 0 else (target - cumulative[lo - 1]) / span
    lat = points[lo - 1][0] + fraction * (points[lo][0] - points[lo - 1][0])
    lon = points[lo - 1][1] + fraction * (points[lo][1] - points[lo - 1][1])
    return (lat, lon)


def local_bearing(points: list[LatLon], cumulative: list[float], target: float) -> float:
    """Bearing of the route near ``target`` miles, used to offset a via point."""
    span = max(5.0, cumulative[-1] * 0.02)
    start = point_at_miles(points, cumulative, max(0.0, target - span))
    end = point_at_miles(points, cumulative, min(cumulative[-1], target + span))
    if haversine(start, end) < 0.05:
        return 0.0
    return bearing(start, end)


def simplify(points: list[LatLon], max_points: int = 1200) -> list[LatLon]:
    """Keep the drawn line light. Checkpoint positions use the full geometry."""
    if len(points) <= max_points:
        return list(points)
    step = math.ceil((len(points) - 1) / (max_points - 1))
    kept = points[::step]
    if kept[-1] != points[-1]:
        kept.append(points[-1])
    return kept

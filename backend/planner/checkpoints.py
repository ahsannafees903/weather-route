"""Place weather checkpoints and the truck's ETA at each one.

Checkpoints include the origin, a point every ``interval`` miles, and the
destination. A leftover shorter than one mile is absorbed into the previous
checkpoint so two markers do not sit on top of each other. The destination
is always included.

Mile marks are scaled to the routing engine's official distance when that
differs from the sum of haversine segments (simplified geometry, or a
different Earth model). ETAs use the fraction of geometry distance, which
is the same fraction after a uniform scale.

Speed is assumed constant: ETA = departure + duration * (miles / total).
That is distance interpolation, not vertex-index interpolation.

Risk miles use backward attribution. The weather sampled at a checkpoint
(the truck's ETA there) colors the segment that ends at that checkpoint.
The origin sample is shown on the map and contributes zero miles.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from planner.geo import LatLon, point_at_miles, polyline_miles


@dataclass(frozen=True)
class CheckpointSlot:
    mile: float
    lat: float
    lon: float
    eta: datetime
    segment_miles: float


def checkpoint_distances(length_miles: float, interval_miles: float) -> list[float]:
    """Mile marks from the origin through the destination."""
    length = float(length_miles)
    interval = float(interval_miles)
    if length <= 0:
        raise ValueError("Route length must be positive.")
    if interval <= 0:
        raise ValueError("Interval must be positive.")

    points = [0.0]
    mark = interval
    while mark < length - 1e-6:
        points.append(mark)
        mark += interval

    remaining = length - points[-1]
    if remaining >= 1.0:
        points.append(length)
    elif points[-1] != length:
        if len(points) == 1:
            points.append(length)
        else:
            points[-1] = length
    return points


def build_checkpoints(
    geometry: list[LatLon],
    interval_miles: float,
    duration_seconds: float,
    departure: datetime,
    official_miles: float | None = None,
) -> list[CheckpointSlot]:
    """Sample the route. ``departure`` must be timezone-aware."""
    if departure.tzinfo is None:
        raise ValueError("departure must be timezone-aware.")
    points, cumulative = polyline_miles(geometry)
    geometry_miles = cumulative[-1]
    official = float(official_miles) if official_miles and official_miles > 0 else geometry_miles
    marks = checkpoint_distances(official, interval_miles)

    slots: list[CheckpointSlot] = []
    previous_display = 0.0
    for index, mile in enumerate(marks):
        display_mile = official if index == len(marks) - 1 else mile
        segment = 0.0 if index == 0 else display_mile - previous_display
        fraction = 0.0 if official == 0 else display_mile / official
        eta = departure + timedelta(seconds=float(duration_seconds) * fraction)
        lat, lon = point_at_miles(points, cumulative, min(geometry_miles, fraction * geometry_miles))
        slots.append(
            CheckpointSlot(
                mile=display_mile,
                lat=lat,
                lon=lon,
                eta=eta,
                segment_miles=segment,
            )
        )
        previous_display = display_mile
    return slots

"""Checkpoint spacing and distance-based ETA interpolation."""

import math
from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase

from planner.checkpoints import build_checkpoints, checkpoint_distances
from planner.geo import EARTH_RADIUS_MILES, haversine, point_at_miles, polyline_miles

MILES_PER_DEGREE_LAT = EARTH_RADIUS_MILES * math.pi / 180
DEPARTURE = datetime(2026, 11, 6, 15, 0, tzinfo=timezone.utc)


def meridian(length_miles: float, lon: float = -105.0, lat0: float = 39.0, kink_at: float | None = None):
    """A northbound line. ``kink_at`` inserts a vertex that is not the midpoint."""
    marks = [0.0]
    if kink_at is not None:
        marks.append(kink_at)
    marks.append(length_miles)
    return [(lat0 + mile / MILES_PER_DEGREE_LAT, lon) for mile in marks]


class CheckpointDistanceTests(SimpleTestCase):
    def test_exact_multiple_includes_both_ends(self):
        self.assertEqual(checkpoint_distances(100, 25), [0.0, 25.0, 50.0, 75.0, 100.0])

    def test_partial_final_segment_is_kept(self):
        self.assertEqual(checkpoint_distances(80, 25), [0.0, 25.0, 50.0, 75.0, 80.0])

    def test_route_shorter_than_the_interval_is_origin_and_destination(self):
        self.assertEqual(checkpoint_distances(10, 50), [0.0, 10.0])

    def test_interval_equal_to_length_has_no_duplicate_destination(self):
        self.assertEqual(checkpoint_distances(50, 50), [0.0, 50.0])

    def test_remainder_under_one_mile_is_absorbed(self):
        marks = checkpoint_distances(100.4, 25)
        self.assertEqual(marks[0], 0.0)
        self.assertEqual(marks[-1], 100.4)
        self.assertNotIn(100.0, marks)
        self.assertEqual(marks, [0.0, 25.0, 50.0, 75.0, 100.4])

    def test_zero_length_is_rejected(self):
        with self.assertRaises(ValueError):
            checkpoint_distances(0, 25)


class InterpolationTests(SimpleTestCase):
    def test_spacing_on_a_real_polyline(self):
        slots = build_checkpoints(meridian(100), 25, 7200, DEPARTURE)
        self.assertEqual([round(slot.mile, 2) for slot in slots], [0, 25, 50, 75, 100])
        gaps = [round(slot.segment_miles, 2) for slot in slots[1:]]
        self.assertEqual(gaps, [25, 25, 25, 25])
        self.assertEqual(slots[0].segment_miles, 0)
        self.assertAlmostEqual(sum(slot.segment_miles for slot in slots), 100, places=6)

    def test_partial_gap_on_an_80_mile_line(self):
        slots = build_checkpoints(meridian(80), 25, 3600, DEPARTURE)
        self.assertEqual([round(slot.mile, 2) for slot in slots], [0, 25, 50, 75, 80])
        self.assertAlmostEqual(slots[-1].segment_miles, 5, places=6)

    def test_eta_uses_distance_fraction_not_vertex_index(self):
        geometry = meridian(100, kink_at=10)
        points, cumulative = polyline_miles(geometry)
        self.assertAlmostEqual(cumulative[-1], 100, places=6)
        # The middle vertex is only 10 miles up the road, not halfway.
        self.assertAlmostEqual(cumulative[1], 10, places=6)

        slots = build_checkpoints(geometry, 50, 10000, DEPARTURE)
        self.assertEqual(len(slots), 3)
        halfway = slots[1]
        self.assertAlmostEqual(halfway.mile, 50, places=6)
        expected_lat = 39.0 + 50 / MILES_PER_DEGREE_LAT
        self.assertAlmostEqual(halfway.lat, expected_lat, places=5)
        kink_lat = 39.0 + 10 / MILES_PER_DEGREE_LAT
        self.assertGreater(abs(halfway.lat - kink_lat), 0.2)
        self.assertEqual(slots[0].eta, DEPARTURE)
        self.assertEqual(halfway.eta, DEPARTURE + timedelta(seconds=5000))
        self.assertEqual(slots[-1].eta, DEPARTURE + timedelta(seconds=10000))

    def test_point_at_miles_matches_haversine_targets(self):
        geometry = meridian(100)
        points, cumulative = polyline_miles(geometry)
        found = point_at_miles(points, cumulative, 40)
        self.assertAlmostEqual(haversine(points[0], found), 40, places=5)

    def test_short_route_still_has_a_destination_checkpoint(self):
        slots = build_checkpoints(meridian(10), 50, 1800, DEPARTURE)
        self.assertEqual(len(slots), 2)
        self.assertEqual(slots[0].mile, 0)
        self.assertAlmostEqual(slots[1].mile, 10, places=5)
        self.assertEqual(slots[1].eta, DEPARTURE + timedelta(seconds=1800))

    def test_official_distance_scales_eta_with_the_displayed_miles(self):
        # Geometry is 100 miles, but the engine reports 80. Mile 40 is halfway
        # along the reported trip, so the ETA is halfway and the point is
        # halfway along the drawn line.
        slots = build_checkpoints(meridian(100), 40, 8000, DEPARTURE, official_miles=80)
        self.assertEqual([round(slot.mile, 2) for slot in slots], [0, 40, 80])
        self.assertEqual(slots[1].eta, DEPARTURE + timedelta(seconds=4000))
        self.assertAlmostEqual(slots[1].lat, 39.0 + 50 / MILES_PER_DEGREE_LAT, places=4)

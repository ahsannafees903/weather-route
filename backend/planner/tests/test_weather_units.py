"""Unit conversion and nearest-hour selection."""

from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase

from planner.timezones import resolve_departure
from planner.weather import (
    nearest_hour_index,
    parse_forecasts,
    precipitation_to_inches,
    snowfall_to_inches,
    wind_to_mph,
)


UTC = timezone.utc


class UnitConversionTests(SimpleTestCase):
    def test_snowfall_centimeters_become_inches(self):
        self.assertAlmostEqual(snowfall_to_inches(2.54, "cm"), 1.0)
        self.assertAlmostEqual(snowfall_to_inches(25.4, "mm"), 1.0)

    def test_snowfall_already_in_inches_is_unchanged(self):
        self.assertEqual(snowfall_to_inches(0.4, "inch"), 0.4)

    def test_precipitation_millimeters_become_inches(self):
        self.assertAlmostEqual(precipitation_to_inches(25.4, "mm"), 1.0)

    def test_wind_kilometers_per_hour_become_mph(self):
        self.assertAlmostEqual(wind_to_mph(100, "km/h"), 62.1371, places=3)

    def test_wind_mph_is_unchanged(self):
        self.assertEqual(wind_to_mph(33, "mp/h"), 33)

    def test_missing_values_are_zero(self):
        self.assertEqual(wind_to_mph(None, "mp/h"), 0)
        self.assertEqual(snowfall_to_inches(None, "cm"), 0)


class ForecastParserTests(SimpleTestCase):
    def test_multi_location_payload_converts_cm_snow_and_keeps_order(self):
        payload = [
            {
                "hourly_units": {
                    "wind_speed_10m": "mp/h",
                    "precipitation": "inch",
                    "snowfall": "cm",
                },
                "hourly": {
                    "time": ["2026-11-06T15:00", "2026-11-06T16:00"],
                    "wind_speed_10m": [10, 20],
                    "precipitation": [0.2, 0],
                    "snowfall": [2.54, 0],
                },
            },
            {
                "hourly_units": {
                    "wind_speed_10m": "km/h",
                    "precipitation": "mm",
                    "snowfall": "inch",
                },
                "hourly": {
                    "time": ["2026-11-06T15:00"],
                    "wind_speed_10m": [16.0934],
                    "precipitation": [2.54],
                    "snowfall": [0.5],
                },
            },
        ]
        parsed = parse_forecasts(payload, [(39.0, -105.0), (40.0, -111.0)])
        first = parsed[(39.0, -105.0)]
        self.assertAlmostEqual(first.snow_in_hr[0], 1.0)
        self.assertEqual(first.rain_in_hr[0], 0.2)
        self.assertEqual(first.wind_mph[1], 20)
        second = parsed[(40.0, -111.0)]
        self.assertAlmostEqual(second.wind_mph[0], 10, places=2)
        self.assertAlmostEqual(second.rain_in_hr[0], 0.1, places=4)
        self.assertEqual(second.snow_in_hr[0], 0.5)

    def test_a_single_object_payload_is_accepted(self):
        payload = {
            "hourly_units": {"wind_speed_10m": "mp/h", "precipitation": "inch", "snowfall": "inch"},
            "hourly": {
                "time": ["2026-11-06T15:00"],
                "wind_speed_10m": [4],
                "precipitation": [0],
                "snowfall": [0],
            },
        }
        parsed = parse_forecasts(payload, [(1.0, 2.0)])
        self.assertEqual(parsed[(1.0, 2.0)].wind_mph, [4])


class NearestHourTests(SimpleTestCase):
    def setUp(self):
        self.times = [
            datetime(2026, 11, 6, 15, tzinfo=UTC),
            datetime(2026, 11, 6, 16, tzinfo=UTC),
            datetime(2026, 11, 6, 17, tzinfo=UTC),
        ]

    def test_exact_hour_matches_itself(self):
        index, clamped = nearest_hour_index(self.times, self.times[1])
        self.assertEqual(index, 1)
        self.assertFalse(clamped)

    def test_tie_keeps_the_earlier_hour(self):
        moment = datetime(2026, 11, 6, 15, 30, tzinfo=UTC)
        index, clamped = nearest_hour_index(self.times, moment)
        self.assertEqual(index, 0)
        self.assertFalse(clamped)

    def test_outside_the_series_is_flagged(self):
        moment = self.times[-1] + timedelta(hours=5)
        index, clamped = nearest_hour_index(self.times, moment)
        self.assertEqual(index, 2)
        self.assertTrue(clamped)


class DepartureTimezoneTests(SimpleTestCase):
    def test_naive_departure_uses_the_origin_zone(self):
        # 6 Nov 2026 is after the US daylight-saving change, so Denver is UTC-7.
        resolved = resolve_departure(datetime(2026, 11, 6, 15, 0), "America/Denver", -104.9)
        self.assertEqual(resolved.utc, datetime(2026, 11, 6, 22, 0, tzinfo=UTC))
        self.assertEqual(resolved.timezone_name, "America/Denver")

    def test_zulu_departure_stays_absolute(self):
        aware = datetime(2026, 11, 6, 15, 0, tzinfo=UTC)
        resolved = resolve_departure(aware, "America/Chicago", -87.6)
        self.assertEqual(resolved.utc, aware)
        self.assertEqual(resolved.timezone_name, "UTC")

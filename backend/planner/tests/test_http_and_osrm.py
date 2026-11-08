"""HTTP retry behavior and OSRM payload parsing."""

from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from planner.exceptions import UpstreamFailure
from planner.geocode import _label
from planner.http_client import get_json
from planner.osrm import parse_osrm, road_summary


class PlaceLabelTests(SimpleTestCase):
    def test_city_label_skips_the_township_in_the_display_name(self):
        hit = {
            "display_name": "Chicago, South Chicago Township, Cook County, Illinois, United States",
            "address": {"city": "Chicago", "state": "Illinois", "country": "United States"},
        }
        self.assertEqual(_label(hit, "Chicago"), "Chicago, Illinois, United States")


class HttpRetryTests(SimpleTestCase):
    def test_retries_a_503_once(self):
        bad = Mock(status_code=503)
        bad.json.return_value = {}
        good = Mock(status_code=200)
        good.json.return_value = {"ok": True}
        with patch("planner.http_client.SESSION.get", side_effect=[bad, good]) as mocked:
            payload = get_json("http://example.test/forecast", service="weather")
        self.assertEqual(payload, {"ok": True})
        self.assertEqual(mocked.call_count, 2)

    def test_second_503_becomes_a_weather_error(self):
        bad = Mock(status_code=503)
        bad.json.return_value = {}
        with patch("planner.http_client.SESSION.get", side_effect=[bad, bad]):
            with self.assertRaises(UpstreamFailure) as caught:
                get_json("http://example.test/forecast", service="weather")
        self.assertIn("weather", str(caught.exception))

    def test_routing_400_body_is_returned_for_the_caller(self):
        denied = Mock(status_code=400)
        denied.json.return_value = {"code": "NoRoute", "message": "No route found"}
        with patch("planner.http_client.SESSION.get", return_value=denied):
            payload = get_json("http://example.test/route", service="routing")
        self.assertEqual(payload["code"], "NoRoute")


class OsrmParserTests(SimpleTestCase):
    def test_coordinates_are_swapped_to_lat_lon(self):
        payload = {
            "code": "Ok",
            "routes": [
                {
                    "distance": 16093.44,
                    "duration": 600,
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[-105.0, 39.0], [-105.0, 39.2]],
                    },
                    "legs": [{"steps": [{"ref": "I 25", "distance": 10000}, {"name": "Main", "distance": 10}]}],
                }
            ],
        }
        routes = parse_osrm(payload)
        self.assertEqual(routes[0].geometry[0], (39.0, -105.0))
        self.assertEqual(routes[0].geometry[1], (39.2, -105.0))
        self.assertAlmostEqual(routes[0].distance_miles, 10, places=4)
        self.assertEqual(routes[0].summary, "I 25 · Main")

    def test_no_route_code_is_empty(self):
        self.assertEqual(parse_osrm({"code": "NoRoute", "routes": []}), [])

    def test_road_summary_ignores_unnamed_segments(self):
        legs = [{"steps": [{"name": "unnamed road", "distance": 500}, {"ref": "US 6", "distance": 20}]}]
        self.assertEqual(road_summary(legs), "US 6")

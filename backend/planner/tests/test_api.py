"""POST /api/plan validation, mocked upstream calls, and wired ranking."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase

from planner.exceptions import UpstreamFailure
from planner.geo import EARTH_RADIUS_MILES, haversine
import math

MILES_PER_DEGREE = EARTH_RADIUS_MILES * math.pi / 180
NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
DEPARTURE = "2026-11-06T15:00:00Z"


def _line(lat0, lon, length_miles=100):
    """GeoJSON [lon, lat] for a two-point northbound line of a known length."""
    return [
        [lon, lat0],
        [lon, lat0 + length_miles / MILES_PER_DEGREE],
    ]


def _meters(coords):
    miles = 0.0
    previous = None
    for lon, lat in coords:
        if previous is not None:
            miles += haversine((previous[1], previous[0]), (lat, lon))
        previous = (lon, lat)
    return miles * 1609.344


def _osrm_route(coords, duration, ref):
    return {
        "distance": _meters(coords),
        "duration": duration,
        "geometry": {"type": "LineString", "coordinates": coords},
        "legs": [
            {
                "steps": [
                    {"ref": ref, "name": ref, "distance": _meters(coords)},
                ]
            }
        ],
    }


def _hours():
    start = datetime(2026, 11, 6, 0, tzinfo=timezone.utc)
    stamps = []
    for offset in range(72):
        stamps.append((start + timedelta(hours=offset)).strftime("%Y-%m-%dT%H:%M"))
    return stamps


HOURS = _hours()
SPIKE = "2026-11-07T03:00"


def _wind(lat, lon, stamp):
    if stamp == SPIKE:
        return 70
    if abs(lon + 105) < 0.2:
        if lat < 39.3:
            return 5
        if lat < 40.0:
            return 40
        return 60
    if abs(lon + 103) < 0.2:
        return 10
    if abs(lon + 107) < 0.2:
        return 36
    return 0


def _forecast_location(lat, lon):
    return {
        "hourly_units": {
            "time": "iso8601",
            "wind_speed_10m": "mp/h",
            "precipitation": "inch",
            "snowfall": "cm",
        },
        "hourly": {
            "time": HOURS,
            "wind_speed_10m": [_wind(lat, lon, stamp) for stamp in HOURS],
            "precipitation": [0] * len(HOURS),
            "snowfall": [0] * len(HOURS),
        },
    }


class Upstream:
    """Scripted Nominatim, OSRM, and Open-Meteo responses."""

    def __init__(self, routes_for_pair, routes_for_via=None, geocode=None):
        self.routes_for_pair = routes_for_pair
        self.routes_for_via = routes_for_via or []
        self.via_calls = 0
        self.calls = []
        if geocode is None:
            geocode = {
                "denver, co": {
                    "lat": "39.7392",
                    "lon": "-104.9903",
                    "display_name": "Denver, Colorado, United States",
                    "address": {"state": "Colorado", "country_code": "us"},
                },
                "salt lake city, ut": {
                    "lat": "40.7608",
                    "lon": "-111.8910",
                    "display_name": "Salt Lake City, Utah, United States",
                    "address": {"state": "Utah", "country_code": "us"},
                },
            }
        self.geocode = geocode

    def __call__(self, url, params=None, headers=None, timeout=None, service=None):
        self.calls.append({"url": url, "params": params, "headers": headers, "service": service})
        if service == "geocoding":
            query = " ".join(str((params or {}).get("q", "")).lower().split())
            hit = self.geocode.get(query)
            return [hit] if hit else []
        if service == "routing":
            path = url.split("/driving/")[1].split("?")[0]
            count = path.count(";") + 1
            if count == 2:
                return {"code": "Ok", "routes": self.routes_for_pair}
            self.via_calls += 1
            if not self.routes_for_via:
                return {"code": "NoRoute", "message": "No route found"}
            route = self.routes_for_via[(self.via_calls - 1) % len(self.routes_for_via)]
            return {"code": "Ok", "routes": [route]}
        if service == "weather":
            lats = [float(item) for item in str(params["latitude"]).split(",") if item]
            lons = [float(item) for item in str(params["longitude"]).split(",") if item]
            return [_forecast_location(lat, lon) for lat, lon in zip(lats, lons)]
        raise AssertionError(f"unexpected service {service}")


def _three_routes():
    return [
        _osrm_route(_line(39.0, -105.0), 7200, "I 80"),
        _osrm_route(_line(39.0, -103.0), 8000, "I 70"),
        _osrm_route(_line(39.0, -107.0), 7600, "US 50"),
    ]


class PlanApiTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def post(self, body, upstream=None):
        payload = json.dumps(body)
        with patch("planner.plan.current_time", return_value=NOW):
            if upstream is None:
                return self.client.post(
                    "/api/plan", data=payload, content_type="application/json"
                )
            with patch("planner.http_client.get_json", side_effect=upstream):
                return self.client.post(
                    "/api/plan", data=payload, content_type="application/json"
                )

    def _body(self, **overrides):
        body = {
            "origin": "Denver, CO",
            "destination": "Salt Lake City, UT",
            "departure": DEPARTURE,
            "load_weight_lb": 20000,
            "interval_miles": 50,
        }
        body.update(overrides)
        return body

    def test_rejects_invalid_json(self):
        response = self.client.post("/api/plan", data="{", content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("JSON", response.json()["error"])

    def test_get_is_not_allowed(self):
        response = self.client.get("/api/plan")
        self.assertEqual(response.status_code, 405)

    def test_health_check(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["plan"], "POST /api/plan")

    def test_missing_and_bad_fields(self):
        cases = [
            ({}, "origin"),
            ({"origin": "Denver, CO"}, "destination"),
            ({"origin": "  ", "destination": "Dallas, TX"}, "origin"),
            (self._body(departure="2026-11-06"), "time"),
            (self._body(departure="yesterday"), "ISO 8601"),
            (self._body(load_weight_lb=-1), "load_weight_lb"),
            (self._body(load_weight_lb="heavy"), "load_weight_lb"),
            (self._body(load_weight_lb=True), "load_weight_lb"),
            (self._body(load_weight_lb=500001), "500000"),
            (self._body(interval_miles=15), "10, 25, or 50"),
            (self._body(interval_miles="wide"), "10, 25, or 50"),
        ]
        for body, needle in cases:
            with self.subTest(body=body):
                response = self.post(body)
                self.assertEqual(response.status_code, 400, response.content)
                self.assertIn(needle, response.json()["error"])

    def test_departure_outside_the_forecast_window(self):
        future = self.post(self._body(departure="2026-12-31T15:00:00Z"))
        self.assertEqual(future.status_code, 400)
        self.assertIn("forecast window", future.json()["error"])
        past = self.post(self._body(departure="2026-11-01T15:00:00Z"))
        self.assertEqual(past.status_code, 400)
        self.assertIn("past", past.json()["error"])

    def test_unknown_place_is_400(self):
        upstream = Upstream(_three_routes(), geocode={})
        response = self.post(self._body(), upstream)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Could not find", response.json()["error"])

    def test_same_place_is_400(self):
        same = {
            "lat": "39.7392",
            "lon": "-104.9903",
            "display_name": "Denver, Colorado, United States",
            "address": {"state": "Colorado", "country_code": "us"},
        }
        upstream = Upstream(
            _three_routes(),
            geocode={"denver, co": same, "salt lake city, ut": same},
        )
        response = self.post(self._body(), upstream)
        self.assertEqual(response.status_code, 400)
        self.assertIn("same place", response.json()["error"])

    def test_geocoder_failure_is_502(self):
        def explode(*args, **kwargs):
            raise UpstreamFailure("The geocoding service failed. Try again in a moment.")

        response = self.post(self._body(), explode)
        self.assertEqual(response.status_code, 502)
        self.assertIn("geocoding", response.json()["error"])

    def test_no_route_is_422(self):
        upstream = Upstream([])
        response = self.post(self._body(), upstream)
        self.assertEqual(response.status_code, 422)
        self.assertIn("did not return a road route", response.json()["error"])

    def test_routing_failure_is_502(self):
        def explode(url, params=None, headers=None, timeout=None, service=None):
            if service == "geocoding":
                return Upstream(_three_routes())(url, params, headers, timeout, service)
            raise UpstreamFailure("The routing service failed. Try again in a moment.")

        response = self.post(self._body(), explode)
        self.assertEqual(response.status_code, 502)
        self.assertIn("routing", response.json()["error"])

    def test_weather_failure_is_502(self):
        def explode(url, params=None, headers=None, timeout=None, service=None):
            if service == "weather":
                raise UpstreamFailure("The weather service failed. Try again in a moment.")
            return Upstream(_three_routes())(url, params, headers, timeout, service)

        response = self.post(self._body(), explode)
        self.assertEqual(response.status_code, 502)
        self.assertIn("weather", response.json()["error"])

    def test_plan_classifies_checkpoints_and_ranks_routes(self):
        upstream = Upstream(_three_routes())
        response = self.post(self._body(), upstream)
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["interval_miles"], 50)
        self.assertEqual(body["load_weight_lb"], 20000)
        self.assertEqual([route["id"] for route in body["routes"]], ["A", "B", "C"])
        self.assertEqual(body["recommended_route_id"], "B")
        self.assertEqual(body["origin"]["timezone"], "America/Denver")

        route_a, route_b, route_c = body["routes"]
        self.assertEqual(
            [point["level"] for point in route_a["checkpoints"]],
            ["low", "high", "no_travel"],
        )
        self.assertEqual([round(point["mile"], 1) for point in route_a["checkpoints"]], [0, 50, 100])
        self.assertEqual(route_a["checkpoints"][0]["eta"], "2026-11-06T15:00:00Z")
        self.assertEqual(route_a["checkpoints"][1]["eta"], "2026-11-06T16:00:00Z")
        self.assertEqual(route_a["checkpoints"][2]["eta"], "2026-11-06T17:00:00Z")
        self.assertAlmostEqual(route_a["miles"]["high"], 50, places=1)
        self.assertAlmostEqual(route_a["miles"]["no_travel"], 50, places=1)
        self.assertEqual(route_a["miles"]["severe"], 0)
        self.assertAlmostEqual(route_a["average_risk"], 3.0, places=2)
        self.assertEqual(route_a["summary"], "I 80")

        self.assertTrue(all(point["level"] == "low" for point in route_b["checkpoints"]))
        self.assertTrue(all(point["level"] == "high" for point in route_c["checkpoints"]))
        self.assertEqual([route["rank"] for route in body["routes"]], [3, 1, 2])
        self.assertTrue(route_b["recommended"])
        self.assertFalse(route_a["recommended"])

        self.assertEqual(body["heatmap"]["hour_count"], 49)
        self.assertGreaterEqual(len(body["heatmap"]["points"]), 3)
        for point in body["heatmap"]["points"]:
            self.assertEqual(len(point["values"]), 49)
            self.assertEqual(point["values"][12], 4)
        calm = next(point for point in body["heatmap"]["points"] if abs(point["lon"] + 103) < 0.2)
        self.assertEqual(calm["values"][0], 0)
        self.assertTrue(all("via" not in note.lower() for note in body["notes"]))

        geocode_headers = [call["headers"] for call in upstream.calls if call["service"] == "geocoding"]
        self.assertTrue(geocode_headers)
        self.assertIn("WeatherAwareTruckRouting", geocode_headers[0]["User-Agent"])
        weather_calls = [call for call in upstream.calls if call["service"] == "weather"]
        self.assertEqual(len(weather_calls), 1)

    def test_default_interval_is_25_miles(self):
        upstream = Upstream(_three_routes())
        body = self._body()
        del body["interval_miles"]
        response = self.post(body, upstream)
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["interval_miles"], 25)
        miles = [point["mile"] for point in payload["routes"][0]["checkpoints"]]
        self.assertEqual(miles, [0, 25, 50, 75, 100])

    def test_heavy_load_escalates_35_to_44_mph_wind(self):
        upstream = Upstream(_three_routes())
        response = self.post(self._body(load_weight_lb=45000), upstream)
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        route_a, route_b, route_c = payload["routes"]
        self.assertEqual(
            [point["level"] for point in route_a["checkpoints"]],
            ["low", "severe", "no_travel"],
        )
        self.assertTrue(all(point["level"] == "severe" for point in route_c["checkpoints"]))
        self.assertIn("load", route_c["checkpoints"][1]["reason"])
        self.assertTrue(all(point["level"] == "low" for point in route_b["checkpoints"]))
        self.assertEqual(payload["recommended_route_id"], "B")

    def test_single_osrm_route_grows_to_three_via_waypoints(self):
        primary = _osrm_route(_line(39.0, -105.0), 7200, "I 80")
        via_routes = [
            _osrm_route(_line(39.0, -103.0), 9000, "I 70"),
            _osrm_route(_line(39.0, -107.0), 9600, "US 50"),
        ]
        upstream = Upstream([primary], via_routes)
        response = self.post(self._body(), upstream)
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(len(payload["routes"]), 3)
        self.assertEqual([route["source"] for route in payload["routes"]], ["osrm", "via", "via"])
        self.assertEqual(upstream.via_calls, 2)
        self.assertTrue(any("via" in note.lower() for note in payload["notes"]))
        self.assertEqual(payload["recommended_route_id"], "B")
        # Route B is the calm via corridor, which beats the primary's No Travel miles.
        self.assertEqual(payload["routes"][1]["summary"], "I 70")

    def test_repeated_plan_is_served_from_cache(self):
        upstream = Upstream(_three_routes())
        with patch("planner.plan.current_time", return_value=NOW):
            with patch("planner.http_client.get_json", side_effect=upstream):
                first = self.client.post(
                    "/api/plan",
                    data=json.dumps(self._body()),
                    content_type="application/json",
                )
                calls_after_first = len(upstream.calls)
                second = self.client.post(
                    "/api/plan",
                    data=json.dumps(self._body()),
                    content_type="application/json",
                )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertGreater(calls_after_first, 0)
        self.assertEqual(len(upstream.calls), calls_after_first)
        self.assertEqual(second.json()["recommended_route_id"], first.json()["recommended_route_id"])

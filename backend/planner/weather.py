"""Open-Meteo hourly forecasts, one multi-coordinate request per uncached batch.

Wind is requested in mph and precipitation in inches. Snowfall is centimeters
on the default API and inches when ``precipitation_unit=inch``. The parser
reads ``hourly_units`` and converts centimeters or millimeters to inches, so
either provider behavior yields inches per hour. Wind values labeled km/h or
m/s are converted to mph as well.

Precipitation and snowfall from Open-Meteo are preceding-hour totals. They
are used as the hourly rate. The hour chosen for an ETA is the nearest
forecast timestamp; an exact tie keeps the earlier hour.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from django.conf import settings
from django.core.cache import cache

from planner import http_client
from planner.exceptions import UpstreamFailure
from planner.geo import LatLon

logger = logging.getLogger(__name__)

_CACHE_SECONDS = 30 * 60
# One multi-coordinate call covers a normal three-route plan. The chunk size
# is only a safety valve for an unusually dense 10-mile sample on a very long haul.
_CHUNK = 300


def wind_to_mph(value: float | None, unit: str) -> float:
    if value is None:
        return 0.0
    number = float(value)
    label = (unit or "").lower()
    if label in {"km/h", "kmh"}:
        return number * 0.621371
    if label in {"m/s", "ms"}:
        return number * 2.23694
    if label in {"kn", "kt", "knots"}:
        return number * 1.15078
    return number


def snowfall_to_inches(value: float | None, unit: str) -> float:
    """Convert a snowfall rate to inches. Centimeters use / 2.54."""
    if value is None:
        return 0.0
    number = float(value)
    label = (unit or "").lower()
    if label in {"cm", "centimeter", "centimeters"}:
        return number / 2.54
    if label in {"mm", "millimeter", "millimeters"}:
        return number / 25.4
    return number


def precipitation_to_inches(value: float | None, unit: str) -> float:
    if value is None:
        return 0.0
    number = float(value)
    label = (unit or "").lower()
    if label in {"mm", "millimeter", "millimeters"}:
        return number / 25.4
    if label in {"cm", "centimeter", "centimeters"}:
        return number / 2.54
    return number


def nearest_hour_index(times: list[datetime], moment: datetime) -> tuple[int, bool]:
    """Index of the closest forecast hour. Ties go to the earlier hour.

    ``clamped`` is true when ``moment`` is more than 30 minutes outside the
    series, so the caller can warn that the forecast did not cover the ETA.
    """
    if not times:
        raise UpstreamFailure("The weather service failed. Try again in a moment.")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    best_index = 0
    best_key: tuple[float, int] | None = None
    for index, stamp in enumerate(times):
        delta = abs((stamp - moment).total_seconds())
        key = (delta, index)
        if best_key is None or key < best_key:
            best_key = key
            best_index = index
    clamped = moment < times[0] - timedelta(minutes=30) or moment > times[-1] + timedelta(minutes=30)
    return best_index, clamped


@dataclass
class Series:
    times: list[datetime]
    wind_mph: list[float]
    rain_in_hr: list[float]
    snow_in_hr: list[float]

    def at(self, moment: datetime) -> tuple[float, float, float, bool]:
        index, clamped = nearest_hour_index(self.times, moment)
        return (
            self.wind_mph[index],
            self.rain_in_hr[index],
            self.snow_in_hr[index],
            clamped,
        )


def _parse_time(value: str) -> datetime:
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _as_location_list(payload) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and payload.get("error"):
        logger.warning("open-meteo error: %s", payload.get("reason"))
        raise UpstreamFailure("The weather service failed. Try again in a moment.")
    if isinstance(payload, dict) and "hourly" in payload:
        return [payload]
    logger.warning("unexpected weather payload type %s", type(payload).__name__)
    raise UpstreamFailure("The weather service failed. Try again in a moment.")


def parse_forecasts(payload, keys: list[LatLon]) -> dict[LatLon, Series]:
    """Align a multi-location Open-Meteo payload with rounded coordinates."""
    locations = _as_location_list(payload)
    if len(locations) != len(keys):
        logger.warning("weather location count %s != %s", len(locations), len(keys))
        raise UpstreamFailure("The weather service failed. Try again in a moment.")
    parsed: dict[LatLon, Series] = {}
    for key, location in zip(keys, locations):
        if location.get("error"):
            raise UpstreamFailure("The weather service failed. Try again in a moment.")
        units = location.get("hourly_units") or {}
        hourly = location.get("hourly") or {}
        stamps = hourly.get("time") or []
        winds = hourly.get("wind_speed_10m") or []
        rains = hourly.get("precipitation") or []
        snows = hourly.get("snowfall") or []
        count = min(len(stamps), len(winds), len(rains), len(snows))
        if count == 0:
            raise UpstreamFailure("The weather service failed. Try again in a moment.")
        wind_unit = str(units.get("wind_speed_10m") or "mp/h")
        rain_unit = str(units.get("precipitation") or "inch")
        snow_unit = str(units.get("snowfall") or "cm")
        parsed[key] = Series(
            times=[_parse_time(stamps[index]) for index in range(count)],
            wind_mph=[wind_to_mph(winds[index], wind_unit) for index in range(count)],
            rain_in_hr=[precipitation_to_inches(rains[index], rain_unit) for index in range(count)],
            snow_in_hr=[snowfall_to_inches(snows[index], snow_unit) for index in range(count)],
        )
    return parsed


def round_key(lat: float, lon: float) -> LatLon:
    return (round(float(lat), 3), round(float(lon), 3))


def _cache_id(key: LatLon, start: datetime, end: datetime) -> str:
    raw = f"{key[0]:.3f}:{key[1]:.3f}:{start.date().isoformat()}:{end.date().isoformat()}"
    return "wx1-" + hashlib.sha256(raw.encode()).hexdigest()


def _store(series: Series) -> dict:
    return {
        "times": [stamp.isoformat() for stamp in series.times],
        "wind_mph": series.wind_mph,
        "rain_in_hr": series.rain_in_hr,
        "snow_in_hr": series.snow_in_hr,
    }


def _load(raw: dict) -> Series:
    return Series(
        times=[_parse_time(value) for value in raw["times"]],
        wind_mph=list(raw["wind_mph"]),
        rain_in_hr=list(raw["rain_in_hr"]),
        snow_in_hr=list(raw["snow_in_hr"]),
    )


def fetch_forecasts(
    points: list[LatLon],
    start: datetime,
    end: datetime,
) -> dict[LatLon, Series]:
    """Fetch every unique rounded coordinate. One HTTP call when the batch fits."""
    unique: list[LatLon] = []
    seen: set[LatLon] = set()
    for lat, lon in points:
        key = round_key(lat, lon)
        if key not in seen:
            seen.add(key)
            unique.append(key)

    found: dict[LatLon, Series] = {}
    missing: list[LatLon] = []
    for key in unique:
        cached = cache.get(_cache_id(key, start, end))
        if cached is not None:
            found[key] = _load(cached)
        else:
            missing.append(key)

    for start_index in range(0, len(missing), _CHUNK):
        chunk = missing[start_index : start_index + _CHUNK]
        params = {
            "latitude": ",".join(f"{lat:.3f}" for lat, _lon in chunk),
            "longitude": ",".join(f"{lon:.3f}" for _lat, lon in chunk),
            "hourly": "wind_speed_10m,precipitation,snowfall",
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "timezone": "UTC",
            "start_date": start.astimezone(timezone.utc).date().isoformat(),
            "end_date": end.astimezone(timezone.utc).date().isoformat(),
        }
        payload = http_client.get_json(
            settings.OPEN_METEO_URL,
            params=params,
            service="weather",
            timeout=60,
        )
        parsed = parse_forecasts(payload, chunk)
        for key, series in parsed.items():
            cache.set(_cache_id(key, start, end), _store(series), _CACHE_SECONDS)
            found[key] = series

    absent = [key for key in unique if key not in found]
    if absent:
        raise UpstreamFailure("The weather service failed. Try again in a moment.")
    return found

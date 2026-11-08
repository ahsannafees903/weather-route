"""Nominatim geocoding with a required User-Agent, a 1 request/second pace, and cache.

Results are cached for seven days. The pace limit applies only on a cache miss,
matching Nominatim's public usage policy.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

from planner import http_client
from planner.exceptions import BadInput, UpstreamFailure
from planner.timezones import timezone_name_for

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_LAST_CALL = 0.0
_CACHE_SECONDS = 7 * 24 * 60 * 60


@dataclass(frozen=True)
class Place:
    query: str
    label: str
    lat: float
    lon: float
    timezone: str


def _normalize(query: str) -> str:
    return " ".join(query.strip().lower().split())


def _throttle() -> None:
    global _LAST_CALL
    interval = float(settings.NOMINATIM_MIN_INTERVAL)
    if interval <= 0:
        return
    with _LOCK:
        wait = interval - (time.monotonic() - _LAST_CALL)
        if wait > 0:
            time.sleep(wait)
        _LAST_CALL = time.monotonic()


def _label(hit: dict, fallback: str) -> str:
    """Prefer city and state over the long Nominatim display name.

    A city such as Chicago is returned with a township in the middle of
    ``display_name`` ("Chicago, South Chicago Township, Cook County"). The
    address fields name the place the driver typed.
    """
    address = hit.get("address") if isinstance(hit.get("address"), dict) else {}
    locality = next(
        (
            address.get(key)
            for key in ("city", "town", "village", "hamlet", "municipality")
            if address.get(key)
        ),
        None,
    )
    state = address.get("state")
    country = address.get("country")
    if locality and state:
        parts = [str(locality), str(state)]
        if country:
            parts.append(str(country))
        return ", ".join(parts)
    display_name = str(hit.get("display_name") or "")
    parts = [part.strip() for part in display_name.split(",") if part.strip()]
    if parts:
        return ", ".join(parts[:3])
    return fallback


def geocode_place(query: str) -> Place:
    """Resolve a free-text place. An empty result is a client error, not a 502."""
    key = "geo2-" + hashlib.sha256(_normalize(query).encode()).hexdigest()
    cached = cache.get(key)
    if cached is not None:
        return Place(**cached)

    _throttle()
    try:
        payload = http_client.get_json(
            settings.NOMINATIM_URL,
            params={
                "q": query,
                "format": "json",
                "limit": 1,
                "addressdetails": 1,
            },
            headers={
                "User-Agent": settings.NOMINATIM_USER_AGENT,
                "Accept": "application/json",
            },
            service="geocoding",
        )
    except UpstreamFailure:
        raise
    except Exception:
        logger.exception("geocoder failed")
        raise UpstreamFailure("The geocoding service failed. Try again in a moment.") from None

    if not isinstance(payload, list) or not payload:
        raise BadInput(
            f"Could not find \"{query}\". Try a city and state, such as Denver, CO."
        )
    hit = payload[0]
    try:
        lat = float(hit["lat"])
        lon = float(hit["lon"])
    except (KeyError, TypeError, ValueError):
        raise BadInput(
            f"Could not find \"{query}\". Try a city and state, such as Denver, CO."
        ) from None

    address = hit.get("address") if isinstance(hit.get("address"), dict) else {}
    place = Place(
        query=query,
        label=_label(hit, query),
        lat=lat,
        lon=lon,
        timezone=timezone_name_for(lat, lon, address),
    )
    cache.set(
        key,
        {
            "query": place.query,
            "label": place.label,
            "lat": place.lat,
            "lon": place.lon,
            "timezone": place.timezone,
        },
        _CACHE_SECONDS,
    )
    return place

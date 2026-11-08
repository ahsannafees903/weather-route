"""Shared HTTP GET with one retry on a transient upstream failure."""

from __future__ import annotations

import logging
import time

import requests
from django.conf import settings

from planner.exceptions import UpstreamFailure

logger = logging.getLogger(__name__)

SESSION = requests.Session()

_USER_MESSAGES = {
    "geocoding": "The geocoding service failed. Try again in a moment.",
    "routing": "The routing service failed. Try again in a moment.",
    "weather": "The weather service failed. Try again in a moment.",
}


def _message(service: str) -> str:
    return _USER_MESSAGES.get(service, "An upstream service failed. Try again in a moment.")


def _read_json(response: requests.Response):
    try:
        return response.json()
    except ValueError:
        return None


def get_json(
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: float | None = None,
    service: str = "upstream",
):
    """GET JSON. Routing HTTP 400 bodies are returned so OSRM codes can be read."""
    timeout = settings.HTTP_TIMEOUT_SECONDS if timeout is None else timeout
    pause = settings.UPSTREAM_RETRY_SLEEP_SECONDS
    last_detail = "request failed"
    for attempt in (1, 2):
        try:
            response = SESSION.get(url, params=params, headers=headers, timeout=timeout)
        except requests.Timeout:
            last_detail = "timed out"
            logger.warning("%s timed out (attempt %s): %s", service, attempt, url)
            if attempt == 1:
                time.sleep(pause)
                continue
            raise UpstreamFailure(_message(service)) from None
        except requests.RequestException as exc:
            last_detail = str(exc)
            logger.warning("%s request error (attempt %s): %s", service, attempt, exc)
            if attempt == 1:
                time.sleep(pause)
                continue
            raise UpstreamFailure(_message(service)) from None

        if response.status_code in {429, 502, 503, 504}:
            last_detail = f"HTTP {response.status_code}"
            logger.warning("%s returned %s (attempt %s)", service, response.status_code, attempt)
            if attempt == 1:
                time.sleep(pause)
                continue
            raise UpstreamFailure(_message(service))

        if response.status_code >= 400:
            payload = _read_json(response)
            if service == "routing" and isinstance(payload, dict) and payload.get("code"):
                return payload
            logger.warning("%s HTTP %s: %s", service, response.status_code, payload)
            raise UpstreamFailure(_message(service))

        payload = _read_json(response)
        if payload is None:
            logger.warning("%s returned non-JSON", service)
            raise UpstreamFailure(_message(service))
        return payload

    logger.warning("%s gave up: %s", service, last_detail)
    raise UpstreamFailure(_message(service))

"""HTTP adapter for the planner. One planning endpoint, plus a health check."""

from __future__ import annotations

import json
import logging

from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_http_methods

from planner.exceptions import BadInput, NoRoute, UpstreamFailure
from planner.plan import build_plan

logger = logging.getLogger(__name__)


def _error(status: int, message: str) -> JsonResponse:
    return JsonResponse({"error": message}, status=status)


@require_GET
def health_view(request):
    """Render's health check. The planning API itself is POST /api/plan only."""
    return JsonResponse(
        {
            "service": "weather-aware-truck-routing",
            "plan": "POST /api/plan",
        }
    )


@require_http_methods(["POST"])
def plan_view(request):
    try:
        payload = json.loads(request.body.decode("utf-8") or "")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error(400, "Request body must be JSON.")
    try:
        result = build_plan(payload)
    except BadInput as exc:
        return _error(400, str(exc))
    except NoRoute as exc:
        return _error(422, str(exc))
    except UpstreamFailure as exc:
        return _error(502, str(exc))
    except Exception:
        logger.exception("plan failed")
        return _error(502, "The planning service failed. Try again in a moment.")
    return JsonResponse(result)

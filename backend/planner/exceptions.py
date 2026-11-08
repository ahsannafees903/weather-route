"""HTTP-mapped errors for the planning API."""


class BadInput(Exception):
    """The request cannot be planned. Respond with HTTP 400."""


class NoRoute(Exception):
    """No drivable route exists between the points. Respond with HTTP 422."""


class UpstreamFailure(Exception):
    """Geocoding, routing, or weather failed. Respond with HTTP 502."""

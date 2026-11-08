"""Origin-local departure times.

Nominatim does not return a timezone. For US addresses we map the state to
the IANA zone that covers most of that state, so daylight saving is handled
by the standard library. A few states span two zones; those edges can be an
hour off and are listed in the README. Outside the US, or when the state is
missing, a fixed offset of round(longitude / 15) hours is used.

A departure string that already carries an offset or a Z is used as an
absolute instant and is not reinterpreted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# Dominant zone for each state. Split-zone states are documented as a limitation.
STATE_TIMEZONES = {
    "alabama": "America/Chicago",
    "alaska": "America/Anchorage",
    "arizona": "America/Phoenix",
    "arkansas": "America/Chicago",
    "california": "America/Los_Angeles",
    "colorado": "America/Denver",
    "connecticut": "America/New_York",
    "delaware": "America/New_York",
    "district of columbia": "America/New_York",
    "florida": "America/New_York",
    "georgia": "America/New_York",
    "hawaii": "Pacific/Honolulu",
    "idaho": "America/Boise",
    "illinois": "America/Chicago",
    "indiana": "America/Indiana/Indianapolis",
    "iowa": "America/Chicago",
    "kansas": "America/Chicago",
    "kentucky": "America/New_York",
    "louisiana": "America/Chicago",
    "maine": "America/New_York",
    "maryland": "America/New_York",
    "massachusetts": "America/New_York",
    "michigan": "America/Detroit",
    "minnesota": "America/Chicago",
    "mississippi": "America/Chicago",
    "missouri": "America/Chicago",
    "montana": "America/Denver",
    "nebraska": "America/Chicago",
    "nevada": "America/Los_Angeles",
    "new hampshire": "America/New_York",
    "new jersey": "America/New_York",
    "new mexico": "America/Denver",
    "new york": "America/New_York",
    "north carolina": "America/New_York",
    "north dakota": "America/Chicago",
    "ohio": "America/New_York",
    "oklahoma": "America/Chicago",
    "oregon": "America/Los_Angeles",
    "pennsylvania": "America/New_York",
    "rhode island": "America/New_York",
    "south carolina": "America/New_York",
    "south dakota": "America/Chicago",
    "tennessee": "America/Chicago",
    "texas": "America/Chicago",
    "utah": "America/Denver",
    "vermont": "America/New_York",
    "virginia": "America/New_York",
    "washington": "America/Los_Angeles",
    "west virginia": "America/New_York",
    "wisconsin": "America/Chicago",
    "wyoming": "America/Denver",
}

STATE_ABBREVIATIONS = {
    "al": "alabama",
    "ak": "alaska",
    "az": "arizona",
    "ar": "arkansas",
    "ca": "california",
    "co": "colorado",
    "ct": "connecticut",
    "de": "delaware",
    "dc": "district of columbia",
    "fl": "florida",
    "ga": "georgia",
    "hi": "hawaii",
    "id": "idaho",
    "il": "illinois",
    "in": "indiana",
    "ia": "iowa",
    "ks": "kansas",
    "ky": "kentucky",
    "la": "louisiana",
    "me": "maine",
    "md": "maryland",
    "ma": "massachusetts",
    "mi": "michigan",
    "mn": "minnesota",
    "ms": "mississippi",
    "mo": "missouri",
    "mt": "montana",
    "ne": "nebraska",
    "nv": "nevada",
    "nh": "new hampshire",
    "nj": "new jersey",
    "nm": "new mexico",
    "ny": "new york",
    "nc": "north carolina",
    "nd": "north dakota",
    "oh": "ohio",
    "ok": "oklahoma",
    "or": "oregon",
    "pa": "pennsylvania",
    "ri": "rhode island",
    "sc": "south carolina",
    "sd": "south dakota",
    "tn": "tennessee",
    "tx": "texas",
    "ut": "utah",
    "vt": "vermont",
    "va": "virginia",
    "wa": "washington",
    "wv": "west virginia",
    "wi": "wisconsin",
    "wy": "wyoming",
}


def timezone_name_for(lat: float, lon: float, address: dict | None) -> str:
    """Pick an IANA name for a geocoded place."""
    info = address or {}
    country = str(info.get("country_code") or "").lower()
    state = str(info.get("state") or info.get("territory") or "").strip().lower()
    state = STATE_ABBREVIATIONS.get(state, state)
    if country in {"us", "usa"} and state in STATE_TIMEZONES:
        return STATE_TIMEZONES[state]
    return _fixed_offset_name(lon)


def _fixed_offset_name(lon: float) -> str:
    hours = max(-12, min(12, round(float(lon) / 15.0)))
    if hours == 0:
        return "Etc/GMT"
    # IANA Etc/GMT signs are inverted: Etc/GMT+7 means UTC-7.
    sign = "-" if hours > 0 else "+"
    return f"Etc/GMT{sign}{abs(hours)}"


def zoneinfo_or_fixed(name: str, lon: float = 0.0):
    try:
        return ZoneInfo(name)
    except Exception:
        hours = max(-12, min(12, round(float(lon) / 15.0)))
        return timezone(timedelta(hours=hours))


@dataclass(frozen=True)
class ResolvedDeparture:
    utc: datetime
    local: datetime
    timezone_name: str


def resolve_departure(value: datetime, origin_tz: str, origin_lon: float = 0.0) -> ResolvedDeparture:
    """Interpret a naive datetime as origin-local. Aware values stay absolute."""
    if value.tzinfo is None:
        zone = zoneinfo_or_fixed(origin_tz, origin_lon)
        local = value.replace(tzinfo=zone)
        return ResolvedDeparture(
            utc=local.astimezone(timezone.utc),
            local=local,
            timezone_name=origin_tz,
        )
    local = value
    name = getattr(value.tzinfo, "key", None)
    if not name:
        offset = value.utcoffset() or timedelta(0)
        total = int(offset.total_seconds())
        if total == 0:
            name = "UTC"
        else:
            sign = "+" if total >= 0 else "-"
            total = abs(total)
            hours, remainder = divmod(total, 3600)
            minutes = remainder // 60
            name = f"UTC{sign}{hours:02d}:{minutes:02d}"
    return ResolvedDeparture(
        utc=local.astimezone(timezone.utc),
        local=local,
        timezone_name=name,
    )

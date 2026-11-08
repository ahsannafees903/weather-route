"""Print a compact summary of two live plans. Requires network access.

    python sample_trips.py
"""

import json
import os
from datetime import datetime, timedelta, timezone

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from planner.plan import build_plan  # noqa: E402

departure = (datetime.now(timezone.utc) + timedelta(hours=3)).replace(minute=0, second=0, microsecond=0)
departure_text = departure.strftime("%Y-%m-%dT%H:%M:%SZ")
trips = [
    ("Denver, CO", "Salt Lake City, UT"),
    ("Chicago, IL", "Dallas, TX"),
]

summaries = []
for origin, destination in trips:
    plan = build_plan(
        {
            "origin": origin,
            "destination": destination,
            "departure": departure_text,
            "load_weight_lb": 35000,
            "interval_miles": 25,
        }
    )
    summary = {
        "origin": plan["origin"]["label"],
        "destination": plan["destination"]["label"],
        "departure_utc": plan["departure"]["utc"],
        "timezone": plan["departure"]["timezone"],
        "load_weight_lb": plan["load_weight_lb"],
        "interval_miles": plan["interval_miles"],
        "recommended_route_id": plan["recommended_route_id"],
        "notes": plan["notes"],
        "heatmap_points": len(plan["heatmap"]["points"]),
        "heatmap_hours": plan["heatmap"]["hour_count"],
        "routes": [
            {
                "id": route["id"],
                "source": route["source"],
                "summary": route["summary"],
                "distance_miles": route["distance_miles"],
                "duration_text": route["duration_text"],
                "miles": route["miles"],
                "average_risk": route["average_risk"],
                "recommended": route["recommended"],
                "rank": route["rank"],
                "checkpoints": len(route["checkpoints"]),
                "levels": {
                    level: sum(1 for point in route["checkpoints"] if point["level"] == level)
                    for level in ("low", "moderate", "high", "severe", "no_travel")
                },
            }
            for route in plan["routes"]
        ],
    }
    summaries.append(summary)
    print(json.dumps(summary, indent=2))
    print("---")

out = os.path.join(os.path.dirname(__file__), "..", "docs", "live-samples.json")
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as handle:
    json.dump({"generated_for_departure_utc": departure_text, "trips": summaries}, handle, indent=2)
    handle.write("\n")
print("wrote", os.path.abspath(out))

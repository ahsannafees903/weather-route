# Weather-Aware Truck Routing

A React + Django app that helps a truck driver pick a road. It builds three driving options, samples wind, rain, and snow every 10, 25, or 50 miles at the truck's estimated arrival time, classifies each checkpoint, and recommends the route with the least weather exposure.

The form takes an origin, a destination, a departure date and time, and a load weight in pounds. The map draws every route, colors each checkpoint by risk, and shows a corridor heatmap for the 48 hours after departure. The slider does not call the server again. All 49 hours come back with the plan.

## Run it locally

Use two terminals. Commands are one per line so they work in Windows PowerShell (PowerShell 5 does not accept `&&`).

Backend:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py test
python manage.py runserver 127.0.0.1:8000
```

Frontend, from the repo root in the other terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open http://127.0.0.1:4178. The dev server reads `VITE_API_URL` or falls back to `http://127.0.0.1:8000`. Copy `frontend/.env.example` to `frontend/.env` only if the API is somewhere else.

On macOS or Linux, create the virtualenv the same way and activate it with `. .venv/bin/activate` instead of the PowerShell `Activate.ps1` line. `tzdata` is in `requirements.txt` because Windows does not ship the IANA timezone database.

Optional live check, after the backend dependencies are installed:

```powershell
cd backend
.\.venv\Scripts\python sample_trips.py
```

That calls the real geocoder, router, and forecast and writes `docs/live-samples.json`.

## Request flow

1. `frontend/src/App.tsx` collects the trip and calls `planTrip`.
2. `frontend/src/api.ts` sends `POST /api/plan` to `VITE_API_URL`.
3. `backend/config/urls.py` routes that POST to `planner/views.py`. A `GET /` health check exists so a host can probe the process. It is not a second planning endpoint.
4. `planner/views.py` parses JSON and maps three exceptions to status codes: `BadInput` → 400, `NoRoute` → 422, `UpstreamFailure` → 502. The body is `{"error": "..."}`.
5. `planner/plan.py` validates the body, then:
   - `planner/geocode.py` resolves both places with Nominatim.
   - `planner/timezones.py` reads a naive departure as local time at the origin. A value that already has `Z` or an offset is kept as an absolute instant.
   - `planner/osrm.py` asks the public OSRM server for up to three driving routes. `planner/geo.py` measures the line and, when OSRM returns fewer than three distinct roads, builds offset via-waypoints.
   - `planner/checkpoints.py` places the origin, every N miles, and the destination, and interpolates each ETA.
   - `planner/weather.py` fetches one Open-Meteo multi-coordinate forecast for every unique checkpoint and heatmap sample.
   - `planner/risk.py` classifies each checkpoint. Load rules can only raise the wind result.
   - `planner/ranking.py` picks the winner.
6. The JSON includes the routes, checkpoint weather, and `heatmap.points[].values` with 49 scores (hour 0 through hour 48).
7. `frontend/src/components/MapView.tsx` draws the lines and the risk markers. `frontend/src/components/HeatmapLayer.tsx` paints hour `h` from data already in memory.

### Files

| File | Role |
| --- | --- |
| `backend/config/settings.py` | Env-based Django settings, CORS, file cache, upstream URLs |
| `backend/config/wsgi.py` | gunicorn entry |
| `backend/planner/risk.py` | Pure threshold and load rules |
| `backend/planner/ranking.py` | Mile buckets and the sort order |
| `backend/planner/checkpoints.py` | Spacing and constant-speed ETAs |
| `backend/planner/geo.py` | Haversine, bearings, point-along-line |
| `backend/planner/geocode.py` | Nominatim, User-Agent, 1 request/second, 7-day cache |
| `backend/planner/osrm.py` | Routes, road names, via-waypoint fill-in, 1-hour cache |
| `backend/planner/weather.py` | Open-Meteo batch, unit conversion, 30-minute cache |
| `backend/planner/timezones.py` | US state → IANA zone, departure resolution |
| `backend/planner/http_client.py` | GET with one retry on 429/502/503/504 |
| `backend/planner/plan.py` | Orchestration and the response shape |
| `backend/planner/views.py` | HTTP adapter |
| `backend/planner/tests/` | Boundaries, spacing, ranking, mocked upstream |
| `frontend/src/App.tsx` | Form, summary cards, loading and error states |
| `frontend/src/components/MapView.tsx` | Routes, markers, popups, legend, slider |
| `frontend/src/components/HeatmapLayer.tsx` | Client-side heatmap |
| `render.yaml` | Render blueprint for the API. Not deployed. |
| `frontend/vercel.json` | Vite build settings for Vercel. Not deployed. |

## APIs

No API keys.

**Nominatim** (`https://nominatim.openstreetmap.org`) turns a place name into a coordinate. It is free and does not need a key. The client sends a descriptive User-Agent, waits 1.1 seconds between uncached calls, and caches hits for seven days. An empty result is a 400, because the place name was the problem. A timeout or HTTP failure is a 502.

**OSRM** (`https://router.project-osrm.org`) returns a driving geometry, distance, duration, and step names. `alternatives=2` asks for two alternates plus the primary route. The public server often returns one or two. When fewer than three distinct roads come back, the server offsets a point to either side of the fastest route (about 25% of the straight-line distance, then a larger offset, then other positions along the line) and requests `origin → via → destination`. A candidate is kept only when a real share of it stays at least 15 miles off the routes already chosen, and when it is not an unreasonable detour (about 1.85× the fastest time or 1.9× the shortest distance, relaxed to 2.4× / 2.6× only if three routes are still missing). At most six via requests are made. The response note says when a route was built this way. The car profile is not a truck profile.

**Open-Meteo** (`https://api.open-meteo.com/v1/forecast`) returns an hourly forecast. Wind is requested in mph and precipitation in inches. Snowfall is centimeters by default and inches when `precipitation_unit=inch`. The parser reads `hourly_units` and converts centimeters with `/ 2.54` (and millimeters with `/ 25.4`) so either behavior yields inches. Many coordinates go in one request. A chunk size of 300 is only a safety valve for a very dense sample. Forecasts are cached per rounded coordinate for 30 minutes.

## Risk rules

Bands are classified in `planner/risk.py`. Where the printed ranges touch, the rule is:

**Wind** is a set of contiguous half-open bands. The printed ranges are integer spans, so 34.9 mph is still Moderate. A value that lands on 25, 35, 45, or 55 starts the higher band.

| Wind | Level |
| --- | --- |
| `< 25 mph` | Low |
| `25 ≤ wind < 35` | Moderate |
| `35 ≤ wind < 45` | High |
| `45 ≤ wind < 55` | Severe |
| `≥ 55 mph` | No Travel |

**Rain and snow** share endpoints in the table (rain 0.25 and 0.50, snow 1.0 and 2.0). A reading that sits in two bands takes the worse band. The top of Severe stays Severe, because No Travel is strictly greater than that end.

| Rain (in/hr) | Level |
| --- | --- |
| `< 0.10` | Low |
| `0.10 ≤ x < 0.25` | Moderate |
| `0.25 ≤ x < 0.50` | High |
| `0.50 ≤ x ≤ 1.00` | Severe |
| `> 1.00` | No Travel |

| Snow (in/hr) | Level |
| --- | --- |
| `< 0.5` | Low |
| `0.5 ≤ x < 1.0` | Moderate |
| `1.0 ≤ x < 2.0` | High |
| `2.0 ≤ x ≤ 3.0` | Severe |
| `> 3.0` | No Travel |

Negative sensor values are treated as zero.

**Load rules apply only to wind, and only raise it.**

- `≥ 55 mph` is No Travel for any load, including an empty truck.
- `45–54 mph` and a load **over** 30,000 lb is No Travel. Exactly 30,000 lb stays Severe.
- `35–44 mph` and a load **over** 40,000 lb is Severe. Exactly 40,000 lb stays High.
- 34.9 mph does not use the 35 mph load rule, even with a heavy trailer.

The checkpoint level is the worst of wind-after-load, rain, and snow. Scores used for the average are Low 0, Moderate 1, High 2, Severe 3, No Travel 4.

**No Travel is worse than Severe.** The published sort list does not name No Travel miles. This app keeps them in their own bucket and sorts them first, so a route with any No Travel miles loses to a route whose worst mile is Severe.

### Recommendation order

Smaller wins. The first difference decides.

1. Fewest No Travel miles.
2. Fewest Severe miles.
3. Fewest High miles.
4. Lowest mileage-weighted average risk.
5. Shortest travel time.
6. Earlier route index, so a complete tie stays on the OSRM order.

Moderate miles matter only through the average. Each mile is in exactly one bucket. No Travel miles are not also counted as Severe.

### Checkpoints and ETAs

Checkpoints include the origin, every selected interval, and the destination. A leftover shorter than one mile is absorbed into the previous checkpoint so two markers do not stack. The destination is always included.

The weather sampled at a checkpoint colors the segment that **ends** there (backward attribution). The origin sample is drawn and contributes zero miles. ETA assumes constant speed: `departure + duration × (mile / total)`. Interpolation follows distance along the polyline, not the vertex index. Mile marks use OSRM's official distance when that differs slightly from the sum of haversine segments.

Open-Meteo precipitation and snowfall are preceding-hour totals. They are used as the hourly rate. The hour chosen for an ETA is the nearest forecast timestamp. An exact tie keeps the earlier hour. If the ETA is more than 30 minutes outside the returned series, the nearest hour is still used and the response says so.

The heatmap uses the same classifier, including the load, at each corridor sample for `departure + 0h` through `departure + 48h`.

## Tests

From `backend`, with the virtualenv active:

```powershell
python manage.py test
```

88 tests cover every wind, rain, and snow threshold including the shared endpoints, both load rules and the exact 30,000 / 40,000 boundaries, combined worst-of, No Travel outranking Severe, the full sort order, checkpoint spacing, sub-mile absorption, distance-based ETA interpolation, unit conversion (cm and mm snow, km/h wind), nearest-hour ties, input validation, 400 / 422 / 502 mapping, a one-call weather batch, cache reuse, and the via-waypoint path when OSRM returns a single road. Upstream HTTP is mocked. Nothing in the test suite calls the network.

## Deployment

Nothing here was deployed, and no hosting account was created.

**API on Render.** In the Render dashboard, create a Blueprint and point it at `render.yaml`. The service root is `backend`. The start command is gunicorn with WhiteNoise. Set `NOMINATIM_USER_AGENT` to a string that identifies your deployment. After the first deploy, copy the service URL.

**UI on Vercel.** Import the repo, set the project root to `frontend`, and leave the framework as Vite (`frontend/vercel.json` already sets the build and output). Add an environment variable:

```text
VITE_API_URL=https://<your-render-service>.onrender.com
```

Vite bakes that value in at build time. Change it and redeploy the frontend. The API allows every origin by default (`CORS_ALLOW_ALL_ORIGINS=true`) so the Vercel URL does not have to be known in advance. Set it to `false` and list `CORS_ALLOWED_ORIGINS` if you want to lock it down.

## Sample results

Live calls on 6 Nov 2026, departure `2026-11-06T06:00:00Z`, load 35,000 lb, sample every 25 miles. The hourly forecast along both corridors was calm (winds under about 11 mph, no rain or snow), so every checkpoint is Low and the sort falls through to travel time. Full JSON is in `docs/live-samples.json`.

**Denver, CO → Salt Lake City, UT.** OSRM returned one road. Two via-waypoints filled the set.

| Route | Source | Roads | Distance | Time | Rank |
| --- | --- | --- | --- | --- | --- |
| A | OSRM | I 80 · I 25 · US 287 | 518.7 mi | 9 h 01 min | Recommended |
| C | via | US 40 · I 70 · CO 9 | 513.1 mi | 11 h 08 min | 2 |
| B | via | I 80 · WY 28 · US 287 | 671.1 mi | 13 h 37 min | 3 |

Route C is a few miles shorter and more than two hours slower, which is the mountain road. Time is the last weather tie-break, so the I-80 option wins. 22 to 28 checkpoints. 86 heatmap points, 49 hours each.

**Chicago, IL → Dallas, TX.** OSRM returned two roads. One via-waypoint added the third.

| Route | Source | Roads | Distance | Time | Rank |
| --- | --- | --- | --- | --- | --- |
| A | OSRM | I 57 · I 30 · I 55 | 966.9 mi | 17 h 06 min | Recommended |
| B | OSRM | I 55 · I 44 · US 69 | 924.6 mi | 17 h 17 min | 2 |
| C | via | I 57 · I 30 · I 40 | 1231.6 mi | 23 h 10 min | 3 |

Route B is shorter in miles and eleven minutes slower, so A wins on time. 155 heatmap points.

Screenshots of the running UI are in `docs/screenshots/` (`denver-popup.webp` shows a mile-275 checkpoint at 10:47 AM MST on the 6:00 AM departure, which is the constant-speed ETA, and `chicago-routes.webp` shows the three Dallas corridors). A later click of the same Denver plan showed Route C at 11 h 05 min; the scripted call above recorded 11 h 08 min. The public router can differ by a few minutes between calls. The roads and the ranking did not change.

## Limitations

- OSRM's public car profile ignores truck height, weight, hazmat, and low bridges. The load weight affects weather risk only.
- ETAs assume a constant speed. They do not model mountain grades or hours-of-service breaks.
- Via-waypoints are geometric offsets, not named alternate corridors. They can be longer. A single-corridor pair can still come back with fewer than three roads, and the note says so.
- A few US states span two time zones (El Paso, the Florida panhandle, western Kansas, and similar edges). The app uses the zone that covers most of the state. Send a departure with an offset when that matters.
- Forecast resolution is one hour. Precipitation is the preceding hour's total, used here as the rate.
- Departures more than 6 hours in the past, or more than 14 days ahead, are rejected because they fall outside the forecast.
- The heatmap is the same risk score as the checkpoints, including load. It is not a raw meteorological field. On a calm day it stays green and the caption says so.
- Drawn lines are lightly simplified. Checkpoint positions use the full geometry.
- Routes that cross the antimeridian are not supported.
- CORS is open by default. There is no authentication.
- Nominatim's public instance allows about one request per second. Repeat trips are served from the cache.

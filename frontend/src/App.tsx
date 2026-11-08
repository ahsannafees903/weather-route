import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import { planTrip } from "./api";
import { MapView } from "./components/MapView";
import { RISK_COLOR, defaultDeparture, formatFixed, formatMiles, routeColor } from "./format";
import type { Plan, PlanRequest } from "./types";

const PRESETS = [
  { label: "Denver → Salt Lake City", origin: "Denver, CO", destination: "Salt Lake City, UT" },
  { label: "Chicago → Dallas", origin: "Chicago, IL", destination: "Dallas, TX" },
];

const INTERVALS = [10, 25, 50] as const;

export default function App() {
  const [origin, setOrigin] = useState("Denver, CO");
  const [destination, setDestination] = useState("Salt Lake City, UT");
  const [departure, setDeparture] = useState(defaultDeparture);
  const [load, setLoad] = useState("35000");
  const [interval, setInterval] = useState<(typeof INTERVALS)[number]>(25);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [hour, setHour] = useState(0);
  const [showHeat, setShowHeat] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const orderedCards = useMemo(() => {
    if (!plan) {
      return [];
    }
    return [...plan.routes].sort((left, right) => left.rank - right.rank);
  }, [plan]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const weight = Number(load);
    if (!origin.trim() || !destination.trim()) {
      setError("Enter both an origin and a destination.");
      return;
    }
    if (!departure) {
      setError("Choose a departure date and time.");
      return;
    }
    if (!Number.isFinite(weight) || weight < 0 || weight > 500000) {
      setError("Load weight must be a number of pounds from 0 to 500,000.");
      return;
    }
    const request: PlanRequest = {
      origin: origin.trim(),
      destination: destination.trim(),
      departure,
      load_weight_lb: weight,
      interval_miles: interval,
    };
    setLoading(true);
    setError(null);
    try {
      const next = await planTrip(request);
      setPlan(next);
      setActiveId(next.recommended_route_id);
      setHour(0);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The plan could not be built.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <p className="brand-kicker">Weather desk</p>
          <h1>Weather-Aware Truck Routing</h1>
        </div>
        <p className="lede">
          Three road options, sampled against wind, rain, and snow at the truck&apos;s ETA, then ranked for the load
          on the trailer.
        </p>
      </header>

      <div className="workspace">
        <section className="panel">
          <form className="trip-form" onSubmit={onSubmit}>
            <div className="presets">
              {PRESETS.map((preset) => (
                <button
                  key={preset.label}
                  type="button"
                  className={
                    origin === preset.origin && destination === preset.destination ? "chip chip-on" : "chip"
                  }
                  onClick={() => {
                    setOrigin(preset.origin);
                    setDestination(preset.destination);
                  }}
                >
                  {preset.label}
                </button>
              ))}
            </div>

            <label>
              Origin
              <input value={origin} onChange={(event) => setOrigin(event.target.value)} required />
            </label>
            <label>
              Destination
              <input value={destination} onChange={(event) => setDestination(event.target.value)} required />
            </label>
            <label>
              Departure
              <span className="hint">Local time at the origin. A clock time with no zone is read that way.</span>
              <input
                type="datetime-local"
                value={departure}
                onChange={(event) => setDeparture(event.target.value)}
                required
              />
            </label>
            <div className="split">
              <label>
                Load weight
                <span className="hint">Pounds</span>
                <input
                  type="number"
                  min={0}
                  max={500000}
                  step={100}
                  value={load}
                  onChange={(event) => setLoad(event.target.value)}
                  required
                />
              </label>
              <fieldset>
                <legend>Sample every</legend>
                <div className="segmented">
                  {INTERVALS.map((miles) => (
                    <button
                      key={miles}
                      type="button"
                      className={miles === interval ? "seg seg-on" : "seg"}
                      onClick={() => setInterval(miles)}
                      aria-pressed={miles === interval}
                    >
                      {miles} mi
                    </button>
                  ))}
                </div>
              </fieldset>
            </div>
            <button className="submit" type="submit" disabled={loading}>
              {loading ? <span className="spinner" aria-hidden="true" /> : null}
              {loading ? "Planning routes…" : "Plan routes"}
            </button>
            {loading ? (
              <p className="status">Geocoding, building three corridors, and sampling the hourly forecast.</p>
            ) : null}
            {error ? (
              <p className="banner" role="alert">
                {error}
              </p>
            ) : null}
          </form>

          {!plan && !loading ? (
            <div className="empty">
              <p>What you get back</p>
              <ol>
                <li>Three distinct driving options. If the router returns fewer, a side via-waypoint fills the set.</li>
                <li>A checkpoint every 10, 25, or 50 miles, colored by the weather the truck meets there.</li>
                <li>
                  A recommendation: fewest No Travel miles, then fewest Severe, then fewest High, then lowest average
                  risk, then shortest time.
                </li>
              </ol>
            </div>
          ) : null}

          {plan ? (
            <div className="results">
              <div className="results-head">
                <h2>Route summary</h2>
                <p>
                  {plan.load_weight_lb.toLocaleString("en-US")} lb · every {plan.interval_miles} miles ·{" "}
                  {plan.departure.timezone}
                </p>
              </div>
              {orderedCards.map((route) => {
                const index = plan.routes.findIndex((item) => item.id === route.id);
                const active = route.id === activeId;
                return (
                  <button
                    key={route.id}
                    type="button"
                    className={
                      "card" + (active ? " card-active" : "") + (route.recommended ? " card-recommended" : "")
                    }
                    onClick={() => setActiveId(route.id)}
                  >
                    <span className="card-rail" style={{ background: routeColor(index) }} />
                    <span className="card-top">
                      <strong>{route.name}</strong>
                      {route.recommended ? <em>Recommended</em> : <span>Choice {route.rank}</span>}
                    </span>
                    <span className="card-summary">{route.summary}</span>
                    <span className="card-metrics">
                      <b>{formatMiles(route.distance_miles)}</b>
                      <b>{route.duration_text}</b>
                      <b>Avg risk {formatFixed(route.average_risk, 2)}</b>
                    </span>
                    <span className="mile-row">
                      <i style={{ background: RISK_COLOR.no_travel }} />
                      No travel {formatMiles(route.miles.no_travel)}
                      <i style={{ background: RISK_COLOR.severe }} />
                      Severe {formatMiles(route.miles.severe)}
                      <i style={{ background: RISK_COLOR.high }} />
                      High {formatMiles(route.miles.high)}
                    </span>
                    <span className="card-source">
                      {route.source === "via" ? "Built with an offset via-waypoint" : "Returned by OSRM"}
                      {route.recommended ? " · highlighted on the map" : ""}
                    </span>
                  </button>
                );
              })}
              {plan.notes.length > 0 ? (
                <ul className="notes">
                  {plan.notes.map((note) => (
                    <li key={note}>{note}</li>
                  ))}
                </ul>
              ) : null}
              <details className="assumptions">
                <summary>How this recommendation is scored</summary>
                <ul>
                  {plan.assumptions.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </details>
            </div>
          ) : null}
        </section>

        <MapView
          plan={plan}
          activeId={activeId}
          hour={hour}
          showHeat={showHeat}
          onHour={setHour}
          onShowHeat={setShowHeat}
        />
      </div>
    </div>
  );
}

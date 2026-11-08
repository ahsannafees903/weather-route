import { memo, useEffect, useMemo } from "react";
import { CircleMarker, MapContainer, Polyline, Popup, TileLayer, useMap, ZoomControl } from "react-leaflet";
import type { Plan, RoutePlan } from "../types";
import { RISK_COLOR, RISK_LABEL, formatFixed, formatWhen, levelFromScore, routeColor } from "../format";
import { HeatmapLayer } from "./HeatmapLayer";

type MapViewProps = {
  plan: Plan | null;
  activeId: string | null;
  hour: number;
  showHeat: boolean;
  onHour: (hour: number) => void;
  onShowHeat: (show: boolean) => void;
};

function FitBounds({ positions, token }: { positions: [number, number][]; token: string }) {
  const map = useMap();
  useEffect(() => {
    if (positions.length > 0) {
      map.fitBounds(positions, { padding: [58, 58] });
    }
  }, [map, positions, token]);
  return null;
}

function ResizeMap() {
  const map = useMap();
  useEffect(() => {
    const fix = () => map.invalidateSize();
    const id = window.setTimeout(fix, 80);
    window.addEventListener("resize", fix);
    return () => {
      window.clearTimeout(id);
      window.removeEventListener("resize", fix);
    };
  }, [map]);
  return null;
}

const RouteShape = memo(function RouteShape({
  route,
  index,
  active,
  timeZone,
}: {
  route: RoutePlan;
  index: number;
  active: boolean;
  timeZone: string;
}) {
  const color = routeColor(index);
  const weight = active ? 7 : route.recommended ? 5 : 4;
  const opacity = active ? 1 : 0.72;
  return (
    <>
      <Polyline
        positions={route.geometry}
        pathOptions={{ color: "#fbf7f1", weight: weight + 4, opacity: active ? 0.95 : 0.55 }}
      />
      <Polyline positions={route.geometry} pathOptions={{ color, weight, opacity }} />
      {route.checkpoints.map((checkpoint) => (
        <CircleMarker
          key={`${route.id}-${checkpoint.mile}`}
          center={[checkpoint.lat, checkpoint.lon]}
          radius={active ? 9 : 7}
          pane="markerPane"
          pathOptions={{
            pane: "markerPane",
            color: "#1e1914",
            weight: 1,
            fillColor: RISK_COLOR[checkpoint.level],
            fillOpacity: 1,
          }}
        >
          <Popup>
            <div className="popup">
              <p className="popup-kicker">
                {route.name} · mile {formatFixed(checkpoint.mile, 0)}
              </p>
              <p className="popup-level" style={{ color: RISK_COLOR[checkpoint.level] }}>
                {RISK_LABEL[checkpoint.level]}
              </p>
              <p className="popup-eta">{formatWhen(checkpoint.eta, timeZone)}</p>
              <dl>
                <div>
                  <dt>Wind</dt>
                  <dd>{formatFixed(checkpoint.wind_mph, 1)} mph</dd>
                </div>
                <div>
                  <dt>Rain</dt>
                  <dd>{formatFixed(checkpoint.rain_in_hr, 2)} in/hr</dd>
                </div>
                <div>
                  <dt>Snow</dt>
                  <dd>{formatFixed(checkpoint.snow_in_hr, 2)} in/hr</dd>
                </div>
              </dl>
              <p className="popup-reason">{checkpoint.reason}</p>
            </div>
          </Popup>
        </CircleMarker>
      ))}
    </>
  );
});

export function MapView({ plan, activeId, hour, showHeat, onHour, onShowHeat }: MapViewProps) {
  const positions = useMemo<[number, number][]>(
    () => (plan ? plan.routes.flatMap((route) => route.geometry) : []),
    [plan],
  );
  const token = plan
    ? `${plan.origin.label}|${plan.destination.label}|${plan.departure.utc}|${plan.interval_miles}`
    : "empty";
  const ordered = useMemo(() => {
    if (!plan) {
      return [];
    }
    return plan.routes
      .map((route, index) => ({ route, index }))
      .sort((left, right) => Number(left.route.id === activeId) - Number(right.route.id === activeId));
  }, [plan, activeId]);

  const peak = useMemo(() => {
    if (!plan) {
      return null;
    }
    let max = 0;
    for (const point of plan.heatmap.points) {
      max = Math.max(max, point.values[hour] ?? 0);
    }
    return levelFromScore(max);
  }, [plan, hour]);

  const timeZone = plan?.departure.timezone ?? "UTC";
  const when = plan ? formatWhen(plan.departure.utc, timeZone, hour) : "";

  return (
    <div className="map-stage">
      <MapContainer
        center={[39.5, -98.35]}
        zoom={4}
        zoomControl={false}
        scrollWheelZoom
        className="map-canvas"
      >
        <TileLayer
          attribution='Tiles &copy; Esri &mdash; Sources: Esri, TomTom, Garmin, FAO, NOAA, USGS, OpenStreetMap contributors'
          url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}"
        />
        <ZoomControl position="topright" />
        <ResizeMap />
        <FitBounds positions={positions} token={token} />
        {plan && showHeat ? (
          <HeatmapLayer points={plan.heatmap.points} hour={hour} enabled={showHeat} />
        ) : null}
        {plan
          ? ordered.map(({ route, index }) => (
              <RouteShape
                key={route.id}
                route={route}
                index={index}
                active={route.id === activeId}
                timeZone={timeZone}
              />
            ))
          : null}
      </MapContainer>

      <aside className="legend">
        <p>Checkpoint risk</p>
        {(Object.keys(RISK_LABEL) as Array<keyof typeof RISK_LABEL>).map((level) => (
          <span key={level}>
            <i style={{ background: RISK_COLOR[level] }} />
            {RISK_LABEL[level]}
          </span>
        ))}
      </aside>

      {plan ? null : <p className="map-caption">Continental view until a trip is planned.</p>}

      <div className="forecast">
        <div className="forecast-head">
          <label htmlFor="forecast-hour">Corridor forecast</label>
          <strong>{plan ? when : "Plan a trip to scrub 0–48h"}</strong>
          {peak ? (
            <em style={{ color: RISK_COLOR[peak] }}>
              {peak === "low" ? "Calm along this corridor" : `Peaks at ${RISK_LABEL[peak]}`}
            </em>
          ) : null}
          <label className="heat-toggle">
            <input
              type="checkbox"
              checked={showHeat}
              onChange={(event) => onShowHeat(event.target.checked)}
              disabled={!plan}
            />
            Heatmap
          </label>
        </div>
        <input
          id="forecast-hour"
          type="range"
          min={0}
          max={48}
          step={1}
          value={hour}
          disabled={!plan}
          aria-valuemin={0}
          aria-valuemax={48}
          aria-valuenow={hour}
          aria-valuetext={plan ? `${hour} hours after departure, ${when}` : "No trip planned"}
          onChange={(event) => onHour(Number(event.target.value))}
        />
        <div className="forecast-scale">
          <span>Departure</span>
          <span>+24h</span>
          <span>+48h</span>
        </div>
      </div>
    </div>
  );
}

export type RiskLevel = "low" | "moderate" | "high" | "severe" | "no_travel";

export type Checkpoint = {
  mile: number;
  lat: number;
  lon: number;
  eta: string;
  eta_local: string;
  wind_mph: number;
  rain_in_hr: number;
  snow_in_hr: number;
  level: RiskLevel;
  segment_miles: number;
  reason: string;
};

export type RoutePlan = {
  id: string;
  name: string;
  source: "osrm" | "via" | string;
  via: { lat: number; lon: number } | null;
  summary: string;
  distance_miles: number;
  duration_seconds: number;
  duration_text: string;
  geometry: [number, number][];
  miles: {
    no_travel: number;
    severe: number;
    high: number;
    moderate: number;
    low: number;
  };
  average_risk: number;
  recommended: boolean;
  rank: number;
  checkpoints: Checkpoint[];
};

export type HeatPoint = {
  lat: number;
  lon: number;
  values: number[];
};

export type Plan = {
  origin: { query: string; label: string; lat: number; lon: number; timezone: string };
  destination: { query: string; label: string; lat: number; lon: number; timezone: string };
  departure: { local: string; utc: string; timezone: string };
  load_weight_lb: number;
  interval_miles: number;
  recommended_route_id: string;
  notes: string[];
  assumptions: string[];
  routes: RoutePlan[];
  heatmap: { hour_count: number; points: HeatPoint[] };
};

export type PlanRequest = {
  origin: string;
  destination: string;
  departure: string;
  load_weight_lb: number;
  interval_miles: 10 | 25 | 50;
};

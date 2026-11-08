import type { RiskLevel } from "./types";

export const RISK_LEVELS = ["low", "moderate", "high", "severe", "no_travel"] as const;

export const RISK_LABEL: Record<RiskLevel, string> = {
  low: "Low",
  moderate: "Moderate",
  high: "High",
  severe: "Severe",
  no_travel: "No Travel",
};

export const RISK_COLOR: Record<RiskLevel, string> = {
  low: "#1f8a4c",
  moderate: "#a07b08",
  high: "#d4650d",
  severe: "#c42828",
  no_travel: "#4c1d6b",
};

export const ROUTE_COLOR = ["#1d4e89", "#0f6e56", "#8a4b08"];

export function routeColor(index: number): string {
  return ROUTE_COLOR[index % ROUTE_COLOR.length] ?? "#1d4e89";
}

export function levelFromScore(score: number): RiskLevel {
  const index = Math.max(0, Math.min(4, Math.round(score)));
  return RISK_LEVELS[index] ?? "low";
}

export function defaultDeparture(): string {
  const date = new Date();
  date.setHours(date.getHours() + 2, 0, 0, 0);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:00`;
}

export function formatWhen(utcIso: string, timeZone: string, hourOffset = 0): string {
  const date = new Date(new Date(utcIso).getTime() + hourOffset * 3_600_000);
  const zone = timeZone && timeZone !== "offset" ? timeZone : "UTC";
  const options: Intl.DateTimeFormatOptions = {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  };
  try {
    return new Intl.DateTimeFormat("en-US", { ...options, timeZone: zone }).format(date);
  } catch {
    return new Intl.DateTimeFormat("en-US", { ...options, timeZone: "UTC" }).format(date);
  }
}

export function formatMiles(value: number): string {
  return `${value.toLocaleString("en-US", { maximumFractionDigits: 1 })} mi`;
}

export function formatFixed(value: number, digits: number): string {
  return value.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

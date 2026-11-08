import type { Plan, PlanRequest } from "./types";

export const API_URL = (import.meta.env.VITE_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

export async function planTrip(request: PlanRequest): Promise<Plan> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}/api/plan`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(request),
      signal: AbortSignal.timeout(90_000),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "TimeoutError") {
      throw new Error("The plan timed out. The forecast service may be busy — try again.");
    }
    throw new Error(
      `Could not reach the planning API at ${API_URL}. Start the Django server and try again.`,
    );
  }

  let payload: { error?: string } | Plan | null = null;
  try {
    payload = (await response.json()) as { error?: string } | Plan;
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const message =
      payload && "error" in payload && payload.error
        ? payload.error
        : `The planning API returned ${response.status}.`;
    throw new Error(message);
  }
  if (!payload || !("routes" in payload)) {
    throw new Error("The planning API returned an unexpected response.");
  }
  return payload;
}

import { useEffect, useRef } from "react";
import type { Layer } from "leaflet";
import { useMap } from "react-leaflet";
import { HeatLayer } from "leaflet.heat";
import type { HeatPoint } from "../types";

const GRADIENT = {
  0.0: "#d7efe2",
  0.2: "#1f8a4c",
  0.48: "#2f9d5a",
  0.62: "#c4960a",
  0.78: "#e06a12",
  0.9: "#d12222",
  1: "#4c1d6b",
};

// Leaflet.heat adds overlapping kernels. A calm corridor has many Low samples
// on top of each other, so Low is kept small enough that a stack stays green,
// while one Severe or No Travel sample still reaches the hot end of the scale.
const INTENSITY = [0.42, 1.35, 2.3, 3.25, 4];

function intensity(score: number): number {
  const index = Math.max(0, Math.min(4, Math.round(score)));
  return INTENSITY[index] ?? 0.42;
}

function toLatLngs(points: HeatPoint[], hour: number): Array<[number, number, number]> {
  return points.map((point) => [point.lat, point.lon, intensity(point.values[hour] ?? 0)]);
}

type HeatmapLayerProps = {
  points: HeatPoint[];
  hour: number;
  enabled: boolean;
};

export function HeatmapLayer({ points, hour, enabled }: HeatmapLayerProps) {
  const map = useMap();
  const layerRef = useRef<HeatLayer | null>(null);

  useEffect(() => {
    if (!map.getPane("heat")) {
      const pane = map.createPane("heat");
      pane.style.zIndex = "350";
      pane.style.pointerEvents = "none";
    }
    if (!enabled) {
      return;
    }
    const layer = new HeatLayer(toLatLngs(points, hour), {
      pane: "heat",
      radius: 16,
      blur: 12,
      max: 4,
      minOpacity: 0.2,
      maxZoom: 5,
      gradient: GRADIENT,
    });
    const asLayer = layer as unknown as Layer;
    map.addLayer(asLayer);
    layerRef.current = layer;
    return () => {
      map.removeLayer(asLayer);
      layerRef.current = null;
    };
    // Hour updates go through setLatLngs so the slider does not rebuild the layer.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, points, enabled]);

  useEffect(() => {
    layerRef.current?.setLatLngs(toLatLngs(points, hour));
  }, [hour, points]);

  return null;
}

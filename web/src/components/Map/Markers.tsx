import { AggregatedSearchResults, getChurchMarkerLabel } from "@/utils";
import L, { Map, Marker as LeafletMarker } from "leaflet";
import { useEffect, useRef } from "react";
import { useMapRouter } from "@/hooks/useMapRouter";
import { useDateFilter } from "@/hooks/useDateFilter";

export const ChurchMarker = ({
  map,
  church: { uuid, latitude, longitude, eventsByDay },
  selected,
}: {
  map: Map;
  church: AggregatedSearchResults["churches"][number];
  selected: boolean;
}) => {
  const router = useMapRouter();
  const markerRef = useRef<LeafletMarker | null>(null);
  const { date } = useDateFilter();

  const firstEventStart = Object.values(eventsByDay || {})?.[0]?.[0]?.start;

  const timeLabel = getChurchMarkerLabel(firstEventStart, date !== null);

  useEffect(() => {
    let marker: LeafletMarker;

    if (timeLabel === null) {
      const emptySize = selected ? 20 : 14;
      const cls = selected
        ? "empty-church-marker-selected"
        : "empty-church-marker";
      marker = L.marker([latitude, longitude], {
        icon: L.divIcon({
          className: "",
          html: `<div class="${cls}"></div>`,
          iconSize: [emptySize, emptySize],
          iconAnchor: [emptySize / 2, emptySize / 2],
        }),
        zIndexOffset: selected ? 1000 : 0,
      })
        .addTo(map)
        .on("click", () => {
          const params = new URLSearchParams(window.location.search);
          params.set("center", `${latitude},${longitude}`);
          router.push(`/church/${uuid}?${params.toString()}`);
        });
    } else {
      const markerClass = selected ? "church-marker-selected" : "church-marker";
      marker = L.marker([latitude, longitude], {
        icon: L.divIcon({
          className: "", // needed to remove the default leaflet class
          html: `<div class="${markerClass}">${timeLabel}</div>`,
          // Zero-size anchor at the coordinate; the pill sizes to its content
          // and is centered above the point via CSS transform.
          iconSize: [0, 0],
          iconAnchor: [0, 0],
          popupAnchor: [0, selected ? -34 : -30],
        }),
        zIndexOffset: selected ? 1000 : 0,
      })
        .addTo(map)
        .on("click", () => {
          const params = new URLSearchParams(window.location.search);
          params.set("center", `${latitude},${longitude}`);
          router.push(`/church/${uuid}?${params.toString()}`);
        });
    }

    markerRef.current = marker;
    return () => {
      marker.remove();
    };
  }, [map, router, uuid, latitude, longitude, timeLabel, selected]);

  useEffect(() => {
    if (!markerRef.current) return;
    if (selected) {
      markerRef.current.openPopup();
    } else {
      markerRef.current.closePopup();
    }
  }, [selected]);

  return null;
};

export const AggregationMarker = ({
  map,
  aggregation: {
    centroid_latitude,
    centroid_longitude,
    church_count,
    max_latitude,
    min_latitude,
    max_longitude,
    min_longitude,
  },
}: {
  map: Map;
  aggregation: AggregatedSearchResults["aggregations"][number];
}) => {
  useEffect(() => {
    const marker = L.marker([centroid_latitude, centroid_longitude], {
      icon: L.divIcon({
        className: "",
        html: `<div class="aggregation-marker-count">${church_count}</div>`,
        iconSize: [25, 25],
        iconAnchor: [12.5, 25], // from to top left, half the width and half the height
      }),
    })
      .addTo(map)
      .on("click", () => {
        map.flyToBounds([
          [max_latitude, min_longitude],
          [min_latitude, max_longitude],
        ]);
      });

    return () => {
      marker.remove();
    };
  }, [
    map,
    centroid_latitude,
    centroid_longitude,
    church_count,
    max_latitude,
    min_latitude,
    max_longitude,
    min_longitude,
  ]);

  return null;
};

export const CurrentPositionMarker = ({
  map,
  position,
}: {
  map: Map;
  position: { latitude: number; longitude: number };
}) => {
  useEffect(() => {
    const marker = L.marker([position.latitude, position.longitude], {
      icon: L.divIcon({
        className: "current-position-marker",
        html: '<div style="background-color: #007bff; width: 20px; height: 20px; border-radius: 50%; border: 3px solid white; box-shadow: 0 0 0 2px #007bff;"></div>',
        iconSize: [20, 20],
        iconAnchor: [10, 10],
      }),
    }).addTo(map);

    return () => {
      marker.remove();
    };
  }, [map, position.latitude, position.longitude]);

  return null;
};

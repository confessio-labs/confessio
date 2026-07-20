import { components } from "@/types";
import { AggregatedSearchResults, Bounds, computeEventsByDay, fetchApi, MAP_TILER_API_KEY, MOBILE_BREAKPOINT } from "@/utils";
import { MaptilerLayer } from "@maptiler/leaflet-maptilersdk";
import L, { Map as LeafletMap } from "leaflet";
import "leaflet-defaulticon-compatibility";
import "leaflet-defaulticon-compatibility/dist/leaflet-defaulticon-compatibility.css";
import "@/lib/leaflet-active-area";
import "leaflet/dist/leaflet.css";
import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ChurchMarker, AggregationMarker, CurrentPositionMarker } from "./Markers";

const getAggregationUuid = (
  aggregation: components["schemas"]["SearchResultOut"]["aggregations"][number],
) => {
  const truncatedLatitude =
    Math.trunc(aggregation.centroid_latitude * 10000) / 10000;
  const truncatedLongitude =
    Math.trunc(aggregation.centroid_longitude * 10000) / 10000;
  return `${truncatedLatitude}-${truncatedLongitude}`;
};

const Map = ({
  setMap,
  searchResults,
  currentPosition,
  initialBounds,
}: {
  setMap: (map: LeafletMap) => void;
  searchResults: AggregatedSearchResults | null | undefined;
  currentPosition: { latitude: number; longitude: number } | null;
  initialBounds: Bounds | null;
}) => {
  const mapRef = useRef<HTMLDivElement>(null);
  const mapInstanceRef = useRef<LeafletMap | null>(null);
  const [mapInstance, setMapInstance] = useState<LeafletMap | null>(null);
  const [tilesReady, setTilesReady] = useState(false);

  const pathname = usePathname();
  const searchParams = useSearchParams();
  const selectedChurchUuid = pathname?.match(/\/church\/([^/]+)/)?.[1];
  const centerParam = searchParams.get("center");

  const selectedChurchInResults = searchResults?.churches.some(
    (c) => c.uuid === selectedChurchUuid,
  );

  // Fetch selected church details to center map and ensure marker stays visible
  const { data: selectedChurchDetails } = useQuery<
    components["schemas"]["ChurchDetails"]
  >({
    queryKey: ["churchDetails", selectedChurchUuid],
    queryFn: () => fetchApi(`/church/${selectedChurchUuid}`),
    enabled: !!selectedChurchUuid,
  });

  useEffect(() => {
    if (mapInstanceRef.current && selectedChurchDetails && !initialBounds) {
      mapInstanceRef.current.setView(
        [selectedChurchDetails.latitude, selectedChurchDetails.longitude],
        16,
      );
    }
  }, [selectedChurchDetails, initialBounds]);

  // Center map when a ?center=lat,lng param is present (from search/marker click)
  useEffect(() => {
    if (!centerParam || !mapInstanceRef.current) return;
    const parts = centerParam.split(",").map(Number);
    const lat = parts[0];
    const lng = parts[1];
    if (lat === undefined || lng === undefined || isNaN(lat) || isNaN(lng))
      return;
    const currentZoom = mapInstanceRef.current.getZoom();
    mapInstanceRef.current.setView([lat, lng], Math.max(currentZoom, 16));
  }, [centerParam]);

  // Values match ModalSheet width (desktop) and collapsed snap point (mobile)
  const getActiveAreaStyles = useCallback((): Partial<CSSStyleDeclaration> => {
    const isDesktop = window.innerWidth >= MOBILE_BREAKPOINT;
    if (isDesktop) {
      return { position: "absolute", top: "0", left: "500px", right: "0", bottom: "0" };
    }
    return { position: "absolute", top: "0", left: "0", right: "0", bottom: "140px" };
  }, []);

  useEffect(() => {
    if (mapRef.current && !mapInstanceRef.current) {
      const startingBounds = initialBounds || {
        north: 48.902,
        west: 2.25,
        south: 48.815,
        east: 2.42,
      };

      const map = L.map(mapRef.current, {
        zoomControl: false,
      });
      map.fitBounds([
        [startingBounds.south, startingBounds.west],
        [startingBounds.north, startingBounds.east],
      ]);

      mapInstanceRef.current = map;
      setMapInstance(map);
      map.setActiveArea(getActiveAreaStyles());
      setMap(map);

      // Expose map instance for E2E testing
      if (process.env.NODE_ENV !== "production") {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (window as any).__map = map;
      }

      // MaptilerLayer requires WebGL2 — check support before creating the
      // layer to avoid a partially-added zombie instance that crashes on events
      const canvas = document.createElement("canvas");
      const gl = canvas.getContext("webgl2");
      if (gl) {
        const layer = new MaptilerLayer({
          apiKey: MAP_TILER_API_KEY || "",
        }).addTo(map);
        // Reveal the map (fade out the shimmer) on first full render.
        try {
          layer.getMaptilerSDKMap().once("load", () => setTilesReady(true));
        } catch {
          setTilesReady(true);
        }
      } else {
        // No WebGL2 → no tile layer to wait for; drop the shimmer immediately.
        setTilesReady(true);
      }
    }
  }, [setMap, initialBounds, getActiveAreaStyles]);

  useEffect(() => {
    const handleResize = () => {
      if (mapInstanceRef.current) {
        mapInstanceRef.current.setActiveArea(getActiveAreaStyles());
      }
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [getActiveAreaStyles]);

  useEffect(() => {
    // adapt map position to current position
    if (mapInstanceRef.current && currentPosition) {
      mapInstanceRef.current.setView(
        [currentPosition.latitude, currentPosition.longitude],
        14,
      );
    }
  }, [currentPosition]);

  return (
    <div className="relative h-full w-full">
      <div ref={mapRef} className="h-full w-full">
        {mapInstance && (
        <>
          {searchResults?.churches.map((church) => (
            <ChurchMarker
              key={church.uuid}
              map={mapInstance}
              church={church}
              selected={church.uuid === selectedChurchUuid}
            />
          ))}
          {selectedChurchDetails && !selectedChurchInResults && (
            <ChurchMarker
              key={selectedChurchDetails.uuid}
              map={mapInstance}
              church={{
                ...selectedChurchDetails,
                eventsByDay: computeEventsByDay(selectedChurchDetails.events),
              }}
              selected
            />
          )}
          {searchResults?.aggregations.map((aggregation) => (
            <AggregationMarker
              key={getAggregationUuid(aggregation)}
              map={mapInstance}
              aggregation={aggregation}
            />
          ))}
          {currentPosition && (
            <CurrentPositionMarker
              map={mapInstance}
              position={currentPosition}
            />
          )}
        </>
        )}
      </div>
      <div
        aria-hidden
        className={`map-shimmer${tilesReady ? " map-shimmer--hidden" : ""}`}
      />
    </div>
  );
};

export default Map;

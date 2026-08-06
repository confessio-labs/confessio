import { cache } from "react";
import { components } from "./types";

const API_URL = "https://confessio.fr/front/api";

// Overridable on non-prod hosts (e.g. a test domain) via NEXT_PUBLIC_SITE_URL.
export const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL ?? "https://confessio.fr";

export const MAP_TILER_API_KEY = process.env.NEXT_PUBLIC_MAP_TILER_API_KEY;
if (MAP_TILER_API_KEY === undefined)
  console.error("MAP_TILER_API_KEY is undefined");

export const MOBILE_BREAKPOINT = 768;

export type Bounds = {
  south: number;
  north: number;
  east: number;
  west: number;
};

export const fetchApi = async (url: string, options: RequestInit = {}) => {
  const response = await fetch(`${API_URL}${url}`, options);
  return response.json();
};

export type AggregatedSearchResults = {
  aggregations: components["schemas"]["SearchResultOut"]["aggregations"];
  churches: (components["schemas"]["SearchResultOut"]["churches"][number] & {
    eventsByDay?: Record<string, components["schemas"]["EventOut"][]>;
  })[];
};

export const computeEventsByDay = (
  events: components["schemas"]["EventOut"][],
): Record<string, components["schemas"]["EventOut"][]> => {
  const today = new Date();
  const sorted = [...events].sort(
    (a, b) => new Date(a.start).getTime() - new Date(b.start).getTime(),
  );

  const eventsByDay: Record<string, components["schemas"]["EventOut"][]> = {};
  for (const event of sorted) {
    const end = event.end ? new Date(event.end) : new Date(event.start);
    if (end < today) continue;
    const dayKey = new Date(event.start).toDateString();
    if (!eventsByDay[dayKey]) eventsByDay[dayKey] = [];
    eventsByDay[dayKey].push(event);
  }
  return eventsByDay;
};

// Ordered by priority — the first matching period names the warning reason.
const HOLIDAY_WARN_PERIODS: {
  period: components["schemas"]["PeriodEnum"];
  label: string;
}[] = [
  { period: "holy_week", label: "pendant la Semaine sainte" },
  { period: "advent", label: "pendant l'Avent" },
  { period: "lent", label: "pendant le Carême" },
  { period: "summer", label: "pendant l'été" },
  { period: "school_holidays", label: "pendant les vacances scolaires" },
];

export const getHolidayWarningReason = (
  periods: components["schemas"]["PeriodEnum"][] | undefined,
): string | null => {
  const active = periods ?? [];
  return (
    HOLIDAY_WARN_PERIODS.find((p) => active.includes(p.period))?.label ?? null
  );
};

export const fetchChurchesWithWebsites = async ({
  min_lat,
  min_lng,
  max_lat,
  max_lng,
  date_filter,
  signal,
}: {
  min_lat: number;
  min_lng: number;
  max_lat: number;
  max_lng: number;
  date_filter?: string;
  signal?: AbortSignal;
}): Promise<AggregatedSearchResults> => {
  const searchParams = new URLSearchParams({
    min_lat: min_lat.toString(),
    min_lng: min_lng.toString(),
    max_lat: max_lat.toString(),
    max_lng: max_lng.toString(),
  });

  if (date_filter) {
    searchParams.append("date_filter", date_filter);
  }

  const response: components["schemas"]["SearchResultOut"] = await fetchApi(
    `/search?${searchParams.toString()}`,
    { signal },
  );
  const churches = response.churches.map((church) => ({
    ...church,
    eventsByDay: computeEventsByDay(church.events),
  }));
  return {
    churches,
    aggregations: response.aggregations,
  };
};

/**
 * Removes the "Église " at the beginning of the name, for readability
 */
export const cleanupChurchName = (churchName: string) =>
  churchName.replace("Église ", "");

export const getFrenchTimeString = (dateString: string) => {
  const date = new Date(dateString);
  return date.toTimeString().split(":00 ")[0]?.replace(":", "h");
};

/**
 * Label shown on a church map pin for its next confession.
 * - With an active date filter: the time (e.g. "10h30").
 * - Otherwise, based on how many calendar days away it is (local time):
 *   - today: the time
 *   - tomorrow: "Demain"
 *   - 2–6 days: the French weekday + day (e.g. "Sam. 15")
 *   - 7+ days: the date as DD/MM (e.g. "02/09")
 * Returns null when there is no upcoming confession.
 */
export const getChurchMarkerLabel = (
  startDateString: string | undefined,
  dateFilterActive: boolean,
): string | null => {
  if (!startDateString) return null;

  const eventDate = new Date(startDateString);
  if (isNaN(eventDate.getTime())) return null;

  if (dateFilterActive) return getFrenchTimeString(startDateString) ?? null;

  const startOfDay = (d: Date) =>
    new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const daysAway = Math.round(
    (startOfDay(eventDate) - startOfDay(new Date())) / 86_400_000,
  );

  if (daysAway <= 0) return getFrenchTimeString(startDateString) ?? null;
  if (daysAway === 1) return "Demain";
  if (daysAway <= 6) {
    const label = eventDate.toLocaleDateString("fr-FR", {
      weekday: "short",
      day: "numeric",
    });
    return label.charAt(0).toUpperCase() + label.slice(1);
  }
  const dd = String(eventDate.getDate()).padStart(2, "0");
  const mm = String(eventDate.getMonth() + 1).padStart(2, "0");
  return `${dd}/${mm}`;
};

/**
 * Creates a nice string to better describe confession times
 */
export const getConfessionTimeString = ({
  start,
  end,
}: {
  start: string;
  end: string | null;
}) =>
  end === null
    ? `à ${getFrenchTimeString(start)}`
    : `de ${getFrenchTimeString(start)} à ${getFrenchTimeString(end)}`;

export const fetchDioceses = cache(
  async (): Promise<components["schemas"]["DioceseOut"][]> => {
    return fetchApi("/dioceses", { cache: "force-cache" });
  },
);

export const fetchDioceseBySlug = cache(
  async (
    slug: string,
  ): Promise<components["schemas"]["DioceseOut"] | null> => {
    const dioceses = await fetchDioceses();
    return dioceses.find((d) => d.slug === slug) ?? null;
  },
);

export const dioceseToBounds = (
  diocese: components["schemas"]["DioceseOut"],
): Bounds => ({
  south: diocese.min_latitude,
  north: diocese.max_latitude,
  west: diocese.min_longitude,
  east: diocese.max_longitude,
});

export const boundsToString = (bounds: Bounds): string =>
  `${bounds.south.toFixed(6)},${bounds.west.toFixed(6)},${bounds.north.toFixed(6)},${bounds.east.toFixed(6)}`;

export const parseBoundsParam = (boundsParam: string | null): Bounds | null => {
  if (!boundsParam) return null;

  const [south, west, north, east] = boundsParam.split(",").map(Number);
  if (
    south === undefined ||
    north === undefined ||
    east === undefined ||
    west === undefined
  )
    return null;

  return { south, west, north, east };
};

import { useQuery } from "@tanstack/react-query";
import { useDateFilter } from "./useDateFilter";
import { useMapBounds } from "./useMapBounds";
import { AggregatedSearchResults, fetchChurchesWithWebsites } from "@/utils";

export const useSearchResults = () => {
  const { bounds } = useMapBounds();
  const { date } = useDateFilter();
  return useQuery<AggregatedSearchResults | null>({
    queryKey: [
      "churches",
      bounds?.south,
      bounds?.west,
      bounds?.north,
      bounds?.east,
      date?.toString(),
    ],
    queryFn: async ({ signal }) => {
      if (!bounds) return Promise.resolve(null);
      return fetchChurchesWithWebsites({
        min_lat: bounds.south,
        max_lat: bounds.north,
        min_lng: bounds.east,
        max_lng: bounds.west,
        date_filter: date?.toISOString().split("T")?.[0] || undefined,
        signal,
      });
    },
    staleTime: 200,
    placeholderData: (previousdata) => previousdata,
  });
};

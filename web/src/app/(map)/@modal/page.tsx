import ModalSheetWrapper from "@/components/ModalSheet/ModalSheetWrapper";
import { fetchChurchesWithWebsites, parseBoundsParam } from "@/utils";

// This is highly dynamic as it depends on the map position. We need the search params, hence the following value
export const dynamic = 'force-dynamic'

export default async function ModalDefault({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const bounds = await searchParams.then(({ bounds }: { bounds?: string }) =>
    parseBoundsParam(bounds || null),
  );
  const initialSearchResults = bounds
    ? await fetchChurchesWithWebsites({
        min_lat: bounds.south,
        max_lat: bounds.north,
        min_lng: bounds.east,
        max_lng: bounds.west,
      })
    : { aggregations: [], churches: [] };
  return <ModalSheetWrapper originalSearchResults={initialSearchResults} />;
}

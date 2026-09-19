import ModalSheetWrapper from "@/components/ModalSheet/ModalSheetWrapper";
import {
  fetchChurchesWithWebsites,
  fetchDioceseBySlug,
  fetchDioceses,
  dioceseToBounds,
} from "@/utils";

export const revalidate = false;

export async function generateStaticParams() {
  const dioceses = await fetchDioceses();
  return dioceses.map((d) => ({ slug: d.slug }));
}

export default async function DiocesModalPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const diocese = await fetchDioceseBySlug(slug);

  if (!diocese) {
    return <ModalSheetWrapper originalSearchResults={{ aggregations: [], churches: [] }} />;
  }

  const bounds = dioceseToBounds(diocese);
  const today = new Date().toISOString().split("T")[0];
  const initialSearchResults = await fetchChurchesWithWebsites({
    min_lat: bounds.south,
    max_lat: bounds.north,
    min_lng: bounds.west,
    max_lng: bounds.east,
    date_filter: today,
  });

  return <ModalSheetWrapper originalSearchResults={initialSearchResults} />;
}

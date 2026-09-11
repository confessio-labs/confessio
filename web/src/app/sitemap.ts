import type { MetadataRoute } from "next";
import { fetchChurchesWithWebsites, fetchDioceses, SITE_URL } from "@/utils";

const BASE_URL = SITE_URL;

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const [{ churches }, dioceses] = await Promise.all([
    fetchChurchesWithWebsites({
      min_lat: 41,
      min_lng: -5.5,
      max_lat: 51.5,
      max_lng: 10,
    }),
    fetchDioceses(),
  ]);

  const churchEntries: MetadataRoute.Sitemap = churches.map((church) => ({
    url: `${BASE_URL}/church/${church.uuid}`,
    changeFrequency: "weekly",
    priority: 0.8,
  }));

  const dioceseEntries: MetadataRoute.Sitemap = dioceses.map((diocese) => ({
    url: `${BASE_URL}/diocese/${diocese.slug}`,
    lastModified: new Date().toISOString().split("T")[0],
    changeFrequency: "daily",
    priority: 0.7,
  }));

  return [
    {
      url: BASE_URL,
      changeFrequency: "daily",
      priority: 1,
    },
    ...dioceseEntries,
    ...churchEntries,
  ];
}

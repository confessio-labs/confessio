import { Metadata } from "next";
import { components } from "@/types";
import { fetchApi } from "@/utils";
import { buildChurchJsonLd } from "@/lib/jsonld";

type ChurchDetails = components["schemas"]["ChurchDetails"];

export async function generateMetadata({
  params,
}: {
  params: Promise<{ uuid: string }>;
}): Promise<Metadata> {
  const { uuid } = await params;
  const church: ChurchDetails = await fetchApi(`/church/${uuid}`);

  const title = `${church.name} — Confessio`;
  const locationParts = [church.address, church.city]
    .filter(Boolean)
    .join(", ");
  const description = locationParts
    ? `Horaires de confession à ${church.name}, ${locationParts}.`
    : `Horaires de confession à ${church.name}.`;

  return {
    title,
    description,
    openGraph: {
      title,
      description,
      url: `/church/${uuid}`,
    },
  };
}

export default async function ChurchPage({
  params,
}: {
  params: Promise<{ uuid: string }>;
}) {
  const { uuid } = await params;
  const church: ChurchDetails = await fetchApi(`/church/${uuid}`);
  const jsonLd = buildChurchJsonLd(church);

  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
    />
  );
}

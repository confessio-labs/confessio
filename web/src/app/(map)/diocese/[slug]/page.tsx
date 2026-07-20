import { fetchDioceseBySlug, fetchDioceses, dioceseToBounds, boundsToString } from "@/utils";
import { notFound } from "next/navigation";
import { Metadata } from "next";
import DioceseRedirect from "./DioceseRedirect";

export const revalidate = false;

export async function generateStaticParams() {
  const dioceses = await fetchDioceses();
  return dioceses.map((d) => ({ slug: d.slug }));
}

type Props = {
  params: Promise<{ slug: string }>;
};

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const diocese = await fetchDioceseBySlug(slug);
  if (!diocese) return {};

  const title = `Confession dans le diocèse de ${diocese.name} — horaires et lieux`;
  const description = `Trouvez les horaires de confession dans le diocèse de ${diocese.name}. Lieux, horaires et informations pratiques pour se confesser près de chez vous.`;

  return {
    title,
    description,
    openGraph: {
      title,
      description,
      type: "website",
      siteName: "Confessio",
    },
  };
}

export default async function DiocesePage({ params }: Props) {
  const { slug } = await params;
  const diocese = await fetchDioceseBySlug(slug);
  if (!diocese) return notFound();

  const bounds = dioceseToBounds(diocese);
  const boundsStr = boundsToString(bounds);

  return <DioceseRedirect boundsStr={boundsStr} />;
}

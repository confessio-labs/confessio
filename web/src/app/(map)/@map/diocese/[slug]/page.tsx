import { Suspense } from "react";
import { fetchDioceseBySlug, fetchDioceses, dioceseToBounds } from "@/utils";
import { HomePage } from "../../default";

export const revalidate = false;

export async function generateStaticParams() {
  const dioceses = await fetchDioceses();
  return dioceses.map((d) => ({ slug: d.slug }));
}

export default async function DioceseMapPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const diocese = await fetchDioceseBySlug(slug);
  const bounds = diocese ? dioceseToBounds(diocese) : null;

  return (
    <Suspense fallback={null}>
      <HomePage serverBounds={bounds} />
    </Suspense>
  );
}

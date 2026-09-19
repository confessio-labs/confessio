import ModalSheet from "@/components/ModalSheet";
import { components } from "@/types";
import { fetchApi } from "@/utils";

export default async function ChurchModal({
  params,
}: {
  params: Promise<{ uuid: string }>;
}) {
  const { uuid } = await params;
  const selectedChurch: components["schemas"]["ChurchDetails"] = await fetchApi(
    `/church/${uuid}`,
  );
  return <ModalSheet selectedChurch={selectedChurch} />;
}

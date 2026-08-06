import { revalidatePath } from "next/cache";
import { fetchDioceses } from "@/utils";

export async function GET(request: Request) {
  const authHeader = request.headers.get("authorization");
  if (authHeader !== `Bearer ${process.env.CRON_SECRET}`) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  const dioceses = await fetchDioceses();

  for (const diocese of dioceses) {
    revalidatePath(`/diocese/${diocese.slug}`);
  }

  return Response.json({ revalidated: dioceses.length });
}

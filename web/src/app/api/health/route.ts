// Shallow on purpose: must not depend on the backend, or a backend blip would
// fail the deploy health-gate and trigger a needless revert.
export const dynamic = "force-dynamic";

export async function GET() {
  return Response.json({
    status: "ok",
    version: process.env.NEXT_PUBLIC_APP_VERSION ?? null,
  });
}

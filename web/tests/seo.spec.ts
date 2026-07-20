import { test, expect, type APIRequestContext } from "@playwright/test";

const DIOCESE_SLUGS = ["paris", "lyon", "marseille"] as const;

// Real church UUIDs sampled from the live API. If any of these gets
// deleted upstream the test will start failing with a 404 — refresh by
// running: curl 'https://confessio.fr/front/api/search?min_lat=48.8&min_lng=2.2&max_lat=48.9&max_lng=2.5'
const CHURCH_UUIDS = [
  "4b312461-8e8b-4caf-9ea5-0690839fd517",
  "878a9ae5-1dc8-4122-9645-5f24db9770d9",
  "be82d4ad-5411-4f9f-baa3-e1cd460291fd",
] as const;

type SeoOptions = {
  titleIncludes?: string;
  descriptionIncludes?: string;
  requireOg?: boolean;
  requireJsonLd?: boolean;
};

async function assertSeo(
  request: APIRequestContext,
  path: string,
  opts: SeoOptions = {},
) {
  const res = await request.get(path, { maxRedirects: 0 });
  expect(res.status(), `${path} should return 200`).toBe(200);

  const html = await res.text();

  expect(
    html,
    `${path} rendered a Next.js error boundary`,
  ).not.toMatch(/__next_error|Application error: a (?:client|server)-side exception/);

  const title = html.match(/<title[^>]*>([^<]*)<\/title>/)?.[1]?.trim();
  expect(title, `${path} missing <title>`).toBeTruthy();
  expect(title!.length, `${path} <title> too short`).toBeGreaterThan(10);
  if (opts.titleIncludes) {
    expect(
      title!.toLowerCase(),
      `${path} <title> should mention "${opts.titleIncludes}"`,
    ).toContain(opts.titleIncludes.toLowerCase());
  }

  const description = html.match(
    /<meta[^>]+name="description"[^>]+content="([^"]*)"/,
  )?.[1];
  expect(description, `${path} missing meta description`).toBeTruthy();
  expect(
    description!.length,
    `${path} meta description too short`,
  ).toBeGreaterThan(40);
  if (opts.descriptionIncludes) {
    expect(description!.toLowerCase()).toContain(
      opts.descriptionIncludes.toLowerCase(),
    );
  }

  if (opts.requireOg !== false) {
    expect(html, `${path} missing og:title`).toMatch(
      /<meta[^>]+property="og:title"/,
    );
    expect(html, `${path} missing og:description`).toMatch(
      /<meta[^>]+property="og:description"/,
    );
  }

  if (opts.requireJsonLd) {
    const jsonLdMatches = [
      ...html.matchAll(
        /<script[^>]+type="application\/ld\+json"[^>]*>([\s\S]*?)<\/script>/g,
      ),
    ];
    expect(
      jsonLdMatches.length,
      `${path} missing JSON-LD <script>`,
    ).toBeGreaterThan(0);
    for (const match of jsonLdMatches) {
      const body = match[1] ?? "";
      expect(
        () => JSON.parse(body),
        `${path} JSON-LD did not parse`,
      ).not.toThrow();
    }
  }

  expect(html.toLowerCase(), `${path} missing <html lang>`).toMatch(
    /<html[^>]+lang="fr"/,
  );
}

test.describe("SEO smoke", () => {
  test("home page", async ({ request }) => {
    await assertSeo(request, "/", {
      titleIncludes: "Confessio",
      descriptionIncludes: "confession",
      requireJsonLd: true,
    });
  });

  test("sitemap.xml", async ({ request }) => {
    const res = await request.get("/sitemap.xml");
    expect(res.status()).toBe(200);
    const xml = await res.text();
    expect(xml).toContain("<urlset");
    expect(xml).toContain("<loc>https://confessio.fr</loc>");

    const locs = [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map(
      (m) => m[1] ?? "",
    );
    const dioceseCount = locs.filter((u) =>
      u.includes("/diocese/"),
    ).length;
    expect(
      dioceseCount,
      "sitemap should expose at least 50 diocese URLs",
    ).toBeGreaterThan(50);
  });

  for (const slug of DIOCESE_SLUGS) {
    test(`diocese page: ${slug}`, async ({ request }) => {
      await assertSeo(request, `/diocese/${slug}`, {
        titleIncludes: "diocèse",
        descriptionIncludes: "confession",
      });
    });
  }

  for (const uuid of CHURCH_UUIDS) {
    test(`church page: ${uuid}`, async ({ request }) => {
      await assertSeo(request, `/church/${uuid}`, {
        titleIncludes: "Confessio",
        requireJsonLd: true,
      });
    });
  }
});

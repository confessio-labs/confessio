import { components } from "@/types";
import { SITE_URL } from "@/utils";

const BASE_URL = SITE_URL;

type ChurchDetails = components["schemas"]["ChurchDetails"];

export function buildChurchJsonLd(church: ChurchDetails) {
  const now = new Date();
  const upcomingEvents = church.events
    .filter((ev) => new Date(ev.end ?? ev.start) >= now)
    .sort((a, b) => new Date(a.start).getTime() - new Date(b.start).getTime())
    .slice(0, 10);

  const address: Record<string, string> = {
    "@type": "PostalAddress",
    addressCountry: "FR",
  };
  if (church.address) address.streetAddress = church.address;
  if (church.zipcode) address.postalCode = church.zipcode;
  if (church.city) address.addressLocality = church.city;

  const jsonLd: Record<string, unknown> = {
    "@context": "https://schema.org",
    "@type": "Church",
    name: church.name,
    url: `${BASE_URL}/church/${church.uuid}`,
    geo: {
      "@type": "GeoCoordinates",
      latitude: church.latitude,
      longitude: church.longitude,
    },
    address,
  };

  if (church.website?.home_url) {
    jsonLd.sameAs = [church.website.home_url];
  }

  if (upcomingEvents.length > 0) {
    jsonLd.event = upcomingEvents.map((ev) => {
      const event: Record<string, unknown> = {
        "@type": "Event",
        name: "Confession",
        startDate: ev.start,
        location: { "@type": "Church", name: church.name },
      };
      if (ev.end) event.endDate = ev.end;
      return event;
    });
  }

  return jsonLd;
}

export const WEBSITE_JSONLD = {
  "@context": "https://schema.org",
  "@type": "WebSite",
  name: "Confessio",
  url: BASE_URL,
  description:
    "Trouvez les horaires de confession catholique près de chez vous.",
  inLanguage: "fr",
  publisher: {
    "@type": "Organization",
    name: "Confessio",
    url: BASE_URL,
    logo: {
      "@type": "ImageObject",
      url: `${BASE_URL}/favicon.svg`,
    },
  },
};

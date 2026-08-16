import type { APIRoute } from "astro";

const sitemapUrl = new URL(
  `${import.meta.env.BASE_URL.replace(/\/$/, "")}/sitemap-index.xml`,
  import.meta.env.SITE,
).href;

const robotsTxt = `
User-agent: *
Allow: /

Sitemap: ${sitemapUrl}
`.trim();

export const GET: APIRoute = () => {
  return new Response(robotsTxt, {
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
    },
  });
};

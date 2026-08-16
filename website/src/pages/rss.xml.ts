import { config } from "@/config";
import { withBase } from "@utils/url";
import rss from "@astrojs/rss";
import { getCollection } from "astro:content";
import type { APIContext } from "astro";

export async function GET(context: APIContext) {
  const pages = await getCollection("pages");

  const sorted = pages.sort(
    (a, b) => (b.data.date?.getTime() ?? 0) - (a.data.date?.getTime() ?? 0)
  );

  return rss({
    title: config.title,
    description: config.description,
    // Channel link is the site root, which lives under the base on Pages.
    site: new URL(
      import.meta.env.BASE_URL,
      context.site ?? "https://lizekai-richard.github.io"
    ),
    items: sorted.map((page) => ({
      title: page.data.title,
      description: page.data.description,
      link: withBase(`/${page.id}/`),
      ...(page.data.date ? { pubDate: page.data.date } : {}),
    })),
    customData: "<language>en</language>",
  });
}

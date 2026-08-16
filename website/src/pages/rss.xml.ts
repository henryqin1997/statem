import { config } from "@/config";
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
    site: context.site ?? new URL("https://statem.dev"),
    items: sorted.map((page) => ({
      title: page.data.title,
      description: page.data.description,
      link: `/${page.id}/`,
      ...(page.data.date ? { pubDate: page.data.date } : {}),
    })),
    customData: "<language>en</language>",
  });
}

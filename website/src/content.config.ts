import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';

/** Long-form pages rendered at /<slug>/ by src/pages/[slug].astro. */
const pageSchema = z.object({
  title: z.string(),
  description: z.string(),
  /** Short label used in the page header, above the title. */
  kicker: z.string().optional(),
  /** Last substantive update; only used for the feed. */
  date: z.coerce.date().optional(),
});

export const collections = {
  pages: defineCollection({
    loader: glob({ pattern: '**/*.{md,mdx}', base: 'src/content/pages' }),
    schema: pageSchema,
  }),
};

import sitemap from "@astrojs/sitemap";
import tailwind from "@astrojs/tailwind";
import Compress from "astro-compress";
import icon from "astro-icon";
import { defineConfig } from "astro/config";
import rehypeAutolinkHeadings from "rehype-autolink-headings";
import rehypeComponents from "rehype-components"; /* Render the custom directive content */
import rehypeKatex from "rehype-katex";
import rehypeSlug from "rehype-slug";
import remarkDirective from "remark-directive"; /* Handle directives */
import remarkGithubAdmonitionsToDirectives from "remark-github-admonitions-to-directives";
import remarkMath from "remark-math";
import remarkSectionize from "remark-sectionize";
import { AdmonitionComponent } from "./src/plugins/rehype-component-admonition.mjs";
import { GithubCardComponent } from "./src/plugins/rehype-component-github-card.mjs";
import { rehypeBaseUrl } from "./src/plugins/rehype-base-url.mjs";
import { parseDirectiveNode } from "./src/plugins/remark-directive-rehype.js";
import mdx from '@astrojs/mdx';

// Deployed as a GitHub Pages project site:
//   https://lizekai-richard.github.io/statem-web/
// The base must match the repository name. Override either value to publish
// elsewhere, e.g.
//   PUBLIC_SITE_URL=https://henryqin1997.github.io PUBLIC_BASE_PATH=/statem pnpm build
//   PUBLIC_BASE_PATH=/ pnpm build            # custom domain or <user>.github.io
const site = process.env.PUBLIC_SITE_URL ?? "https://lizekai-richard.github.io";
const base = process.env.PUBLIC_BASE_PATH ?? "/statem-web";

export default defineConfig({
  site,
  base,
  trailingSlash: "always",
  integrations: [
    tailwind({
      nesting: true,
      applyBaseStyles: false,
    }),
    icon({
      include: {
        "fa6-brands": ["*"],
        "fa6-regular": ["*"],
        "fa6-solid": ["*"],
      },
    }),
    sitemap(),
    Compress({
      CSS: true,
      Image: false,
      Action: {
        Passed: async () => true, // https://github.com/PlayForm/Compress/issues/376
      },
    }),
    mdx(),
  ],
  markdown: {
    shikiConfig: {
      themes: {
        light: 'github-light',
        dark: 'github-dark',
      },
    },
    remarkPlugins: [
      remarkMath,
      remarkGithubAdmonitionsToDirectives,
      remarkDirective,
      remarkSectionize,
      parseDirectiveNode,
    ],
    rehypePlugins: [
      rehypeKatex,
      rehypeSlug,
      [rehypeBaseUrl, { base }],
      [
        rehypeComponents,
        {
          components: {
            github: GithubCardComponent,
            note: (x, y) => AdmonitionComponent(x, y, "note"),
            tip: (x, y) => AdmonitionComponent(x, y, "tip"),
            important: (x, y) => AdmonitionComponent(x, y, "important"),
            caution: (x, y) => AdmonitionComponent(x, y, "caution"),
            warning: (x, y) => AdmonitionComponent(x, y, "warning"),
            // remark-github-admonitions-to-directives maps `> [!CAUTION]` to a
            // `danger` directive; without this it renders as a literal <danger> tag.
            danger: (x, y) => AdmonitionComponent(x, y, "caution"),
          },
        },
      ],
      [
        rehypeAutolinkHeadings,
        {
          behavior: "append",
          properties: {
            className: ["anchor"],
          },
        },
      ],
    ],
  },
  vite: {
    build: {
      rollupOptions: {
        onwarn(warning, warn) {
          // temporarily suppress this warning
          if (
            warning.message.includes("is dynamically imported by") &&
            warning.message.includes("but also statically imported by")
          ) {
            return;
          }
          warn(warning);
        },
      },
    },
  },
});

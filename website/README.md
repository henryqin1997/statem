# StateM project site

Static Astro site for StateM. Three pages: a landing page, a method deep-dive, and the full
results with disclosure.

Astro 5 + Tailwind + MDX. The layout and content components derive from the open-source
[Fuwari](https://github.com/saicaca/fuwari) template (MIT).

## Develop

Requires Node 20+ and pnpm (the repo enforces pnpm via `only-allow`; `corepack enable pnpm` if
you do not have it).

```bash
pnpm install
pnpm dev      # http://localhost:4321
pnpm build    # static output in dist/
pnpm preview  # serve dist/
```

## Where the content lives

| What | File |
| --- | --- |
| Site name, nav, paper/repo links | `src/config.ts` |
| Landing page prose | `src/content/main/home.mdx` |
| Landing hero, headline numbers | `src/pages/index.astro` |
| Method page | `src/content/pages/method.mdx` |
| Results page | `src/content/pages/results.mdx` |
| Figures | `public/assets/figures/` |
| Paper PDF | `public/statem.pdf` |

Adding a page means dropping a new `.mdx` file in `src/content/pages/`; it is routed at
`/<filename>/` by `src/pages/[slug].astro` and picks up every MDX component automatically.
The header carries only the theme toggle, so link to a new page from the body or the hero.
Its h2/h3 headings automatically become the left-margin outline on viewports ≥1200px.

## Components available in MDX

No imports needed — `src/pages/[slug].astro` and `src/pages/index.astro` inject them.

- `<StateGraph>` — the runbook state machine diagram (inline SVG, theme-aware)
- `<NodeAnatomy>` — the in_hook / body / out_hook / before_transfer breakdown
- `<StatGrid stats={[...]} cols={4}>` — headline number tiles
- `<ColumnChart>` — grouped bars; supports `minValue` for a truncated axis
- `<BarChart>`, `<LineChart>` — stacked horizontal bars, line/multi-panel charts
- `<Figure src caption width invertOnDark frame>` — captioned image
- `<Table caption>` — wraps a markdown table
- `<Grid cols gap>` — side-by-side blocks
- `<Tabs>` with `<div data-label="...">` children
- `<Video src>` — YouTube/mp4 embed

Markdown extras: KaTeX math, GitHub alerts (`> [!NOTE]`, `> [!WARNING]`, `> [!CAUTION]`),
`:::note`-style directives, shiki highlighting with copy buttons.

### Two gotchas

- **`<Figure>` inverts images in dark mode by default.** That is right for white-background line
  art and wrong for colored plots, screenshots, and photos — pass `invertOnDark={false} frame`
  for those, which puts the image on a light card instead.
- **`$` in MDX prose can be parsed as math.** Escape it: `\$15`.

## Deploy

Built as static files; `wrangler.jsonc` is set up for Cloudflare Workers static assets.

```bash
pnpm build
npx wrangler deploy
```

## Before launch

- [ ] Set the real domain in `astro.config.mjs` (`site:`) — it currently reads
      `https://statem.dev` and feeds canonical URLs, OG tags, the sitemap, and the feed.
- [ ] Point `paper` in `src/config.ts` at the arXiv page once it exists, instead of the bundled
      `public/statem.pdf`.
- [ ] Update the Terminal-Bench submission link if PR #142 is merged or superseded.

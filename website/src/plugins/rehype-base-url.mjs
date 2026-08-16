import { visit } from "unist-util-visit";

/** Prefix root-relative hrefs/srcs in markdown with the site base.
 *
 *  Astro applies `base` to the routes it generates, but a link written as
 *  `[method](/method/)` in MDX is passed through verbatim and would 404 when
 *  the site is served from a subpath. This rewrites those at build time.
 *  Component props (e.g. <Figure src="...">) are not HTML at this stage and
 *  are handled inside the components themselves.
 */
export function rehypeBaseUrl(options = {}) {
  const base = (options.base ?? "/").replace(/\/$/, "");

  return (tree) => {
    if (!base) return;

    visit(tree, "element", (node) => {
      for (const attr of ["href", "src"]) {
        const value = node.properties?.[attr];
        if (typeof value !== "string") continue;
        // Only site-root paths: skip protocol-relative, external, anchors, and
        // anything already carrying the prefix.
        if (!value.startsWith("/") || value.startsWith("//")) continue;
        if (value === base || value.startsWith(`${base}/`)) continue;
        node.properties[attr] = `${base}${value}`;
      }
    });
  };
}

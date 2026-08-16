/** Resolve a site-root-relative path against the configured base.
 *
 *  The site is served from a subpath on GitHub Pages
 *  (https://<user>.github.io/statem/), so every absolute path written as
 *  "/assets/x.png" has to become "/statem/assets/x.png". Astro rewrites the
 *  routes it generates, but not paths we hardcode, so those go through here.
 */
export function withBase(path: string): string {
  if (!path.startsWith("/")) return path;
  const base = import.meta.env.BASE_URL.replace(/\/$/, "");
  return `${base}${path}`;
}

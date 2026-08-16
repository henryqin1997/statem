/** Shared utilities for chart components. */

/** Observe elements and add 'is-visible' class when they scroll into view. */
export function observeCharts(
  selector: string,
  opts?: { threshold?: number; onVisible?: (el: Element) => void }
) {
  const elements = document.querySelectorAll(selector);
  if (!elements.length) return;

  const threshold = opts?.threshold ?? 0.2;
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          opts?.onVisible?.(entry.target);
          observer.unobserve(entry.target);
        }
      });
    },
    { threshold }
  );

  elements.forEach((el) => observer.observe(el));
  return observer;
}

/** Create a tooltip element and attach it to a container.
 *  Returns helpers for showing/hiding/positioning.
 *  Works with both mouse and touch events. */
export function createTooltip(container: Element) {
  const tip = document.createElement("div");
  tip.className = "chart-tip";
  container.appendChild(tip);

  function positionAt(clientX: number, clientY: number) {
    const rect = container.getBoundingClientRect();
    let x = clientX - rect.left + 12;
    let y = clientY - rect.top - 8;
    const tw = tip.offsetWidth;
    const th = tip.offsetHeight;
    if (x + tw > rect.width - 4) x = rect.width - tw - 4;
    if (x < 4) x = 4;
    if (y + th > rect.height - 4) y = clientY - rect.top - th - 12;
    if (y < 4) y = 4;
    tip.style.left = x + "px";
    tip.style.top = y + "px";
  }

  return {
    el: tip,
    show(html: string) {
      tip.innerHTML = html;
      tip.style.display = "block";
    },
    hide() {
      tip.style.display = "none";
    },
    position(e: MouseEvent | TouchEvent) {
      const pt = "touches" in e ? e.touches[0] : e;
      if (pt) positionAt(pt.clientX, pt.clientY);
    },
  };
}

/** Attach hover+touch tooltip to an element.
 *  Handles mouseenter/move/leave and touchstart/end uniformly. */
export function attachTooltip(
  el: Element,
  tooltip: ReturnType<typeof createTooltip>,
  opts: {
    onEnter: () => string;
    onLeave?: () => void;
  }
) {
  el.addEventListener("mouseenter", () => tooltip.show(opts.onEnter()));
  el.addEventListener("mousemove", (e) => tooltip.position(e as MouseEvent));
  el.addEventListener("mouseleave", () => { tooltip.hide(); opts.onLeave?.(); });

  el.addEventListener("touchstart", (e) => {
    tooltip.show(opts.onEnter());
    tooltip.position(e as TouchEvent);
  }, { passive: true });
  el.addEventListener("touchend", () => { tooltip.hide(); opts.onLeave?.(); });
}

/** Format a number for display. Integers stay whole, small decimals get
 *  enough precision to be distinguishable, larger decimals get 2 places. */
export function fmtValue(v: number): string {
  if (Number.isInteger(v)) return v.toString();
  if (Math.abs(v) >= 0.01) return v.toFixed(2);
  return v.toFixed(3);
}

/** Build the sizing style string for the chart wrapper. */
export function sizerStyle(width?: number): string | undefined {
  if (!width) return undefined;
  return `max-width:min(calc(${width} * var(--page-width, 100%)), 100%)`;
}

import { useEffect, useRef } from "react";

/**
 * Keep a scroll container pinned to the bottom while content streams in — but
 * only while the user is *already* at the bottom. The moment they scroll up to
 * read something, sticking is disabled until they come back down, so the page
 * never yanks itself out from under the mouse.
 */
export function useStickyScroll(
  active: boolean,
  deps: unknown[],
  { selector = ".content", threshold = 60 }: { selector?: string; threshold?: number } = {},
) {
  const stick = useRef(true);
  const elRef = useRef<HTMLElement | null>(null);

  // Track whether the user is parked at the bottom.
  useEffect(() => {
    const el = document.querySelector(selector) as HTMLElement | null;
    elRef.current = el;
    if (!el) return;
    const atBottom = () => el.scrollHeight - el.scrollTop - el.clientHeight <= threshold;
    stick.current = atBottom();
    const onScroll = () => { stick.current = atBottom(); };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [selector, threshold]);

  useEffect(() => {
    if (!active || !stick.current) return;
    const el = elRef.current;
    if (!el) return;
    // rAF so it runs after the streamed nodes are laid out
    const id = requestAnimationFrame(() => {
      el.scrollTop = el.scrollHeight;
    });
    return () => cancelAnimationFrame(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, ...deps]);
}

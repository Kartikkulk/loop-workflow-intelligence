"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Reveals its children the first time they scroll into view.
 *
 * Once only — re-animating on every scroll past is the thing that makes an
 * animated page tiring to read. Honours `prefers-reduced-motion` by rendering
 * the content immediately, and falls back to visible when IntersectionObserver
 * is unavailable, so no content is ever hidden by a failed animation.
 */
export function Reveal({
  children,
  delay = 0,
  className = "",
}: {
  children: React.ReactNode;
  delay?: number;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduced || typeof IntersectionObserver === "undefined") {
      setShown(true);
      return;
    }
    const node = ref.current;
    if (!node) return;

    // A safety net, because this component's initial state is invisible. If the
    // observer never fires — a browser quirk, a layout that never intersects,
    // an element already past the viewport on a restored scroll position — the
    // content would stay hidden forever. Losing an animation is a small cost;
    // losing the page is not, and this file has already caused that once.
    const failsafe = setTimeout(() => setShown(true), 1600);

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setShown(true);
          clearTimeout(failsafe);
          observer.disconnect();
        }
      },
      { rootMargin: "0px 0px -12% 0px", threshold: 0.05 },
    );
    observer.observe(node);
    return () => {
      clearTimeout(failsafe);
      observer.disconnect();
    };
  }, []);

  return (
    <div
      ref={ref}
      className={className}
      style={
        shown
          ? { animation: `fade-up 700ms cubic-bezier(0.16,1,0.3,1) ${delay}ms both` }
          : { opacity: 0 }
      }
    >
      {children}
    </div>
  );
}

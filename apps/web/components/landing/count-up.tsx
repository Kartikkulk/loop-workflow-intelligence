"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Counts a number up once, the first time it scrolls into view.
 *
 * The final value is rendered on the server and is what a reader with motion
 * disabled — or with JavaScript still loading — sees. The animation only ever
 * counts *to* a number that was already correct, so nothing here can make a
 * figure look different from what the product measured.
 */
export function CountUp({
  to,
  decimals = 0,
  suffix = "",
  durationMs = 1400,
}: {
  to: number;
  decimals?: number;
  suffix?: string;
  durationMs?: number;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const [value, setValue] = useState(to);

  useEffect(() => {
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduced || typeof IntersectionObserver === "undefined") return;

    const node = ref.current;
    if (!node) return;

    setValue(0);
    let frame = 0;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return;
        observer.disconnect();
        const started = performance.now();
        const tick = (now: number) => {
          const progress = Math.min(1, (now - started) / durationMs);
          // Ease-out cubic: fast at first, settling rather than stopping dead.
          setValue(to * (1 - Math.pow(1 - progress, 3)));
          if (progress < 1) frame = requestAnimationFrame(tick);
        };
        frame = requestAnimationFrame(tick);
      },
      { threshold: 0.4 },
    );
    observer.observe(node);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
    };
  }, [to, durationMs]);

  return (
    <span ref={ref} className="tabular-nums">
      {value.toFixed(decimals)}
      {suffix}
    </span>
  );
}

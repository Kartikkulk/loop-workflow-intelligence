import type { Config } from "tailwindcss";

/**
 * The palette is defined once here and consumed everywhere. Values are chosen
 * for a dark, dense operations console: a near-black ground, a single restrained
 * accent, and semantic colours reserved for state rather than decoration.
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#08090b",
          900: "#0c0e12",
          850: "#11141a",
          800: "#161a21",
          700: "#1e232c",
          600: "#2a3140",
          500: "#3a4354",
          400: "#4d5768",
        },
        mist: {
          500: "#6b7688",
          400: "#8b96a8",
          300: "#aab3c2",
          200: "#c9d0da",
          100: "#e8ecf1",
        },
        accent: {
          600: "#2563eb",
          500: "#3b82f6",
          400: "#60a5fa",
          300: "#93c5fd",
        },
        good: { 600: "#059669", 500: "#10b981", 400: "#34d399", 300: "#6ee7b7" },
        warn: { 600: "#d97706", 500: "#f59e0b", 400: "#fbbf24", 300: "#fcd34d" },
        bad: { 600: "#dc2626", 500: "#ef4444", 400: "#f87171", 300: "#fca5a5" },
        // A second data hue, so a chart with two series does not have to
        // borrow the interactive accent for one of them.
        cyan: { 600: "#0891b2", 500: "#06b6d4", 400: "#22d3ee" },
      },
      boxShadow: {
        // Elevation on a near-black ground has to come from a lifted edge
        // rather than a drop shadow, which is invisible at these values.
        lift: "0 1px 0 0 rgba(255,255,255,0.04) inset, 0 8px 24px -12px rgba(0,0,0,0.7)",
        glow: "0 0 0 1px rgba(59,130,246,0.35), 0 0 20px -4px rgba(59,130,246,0.35)",
      },
      keyframes: {
        shimmer: {
          "0%": { backgroundPosition: "-160% 0" },
          "100%": { backgroundPosition: "260% 0" },
        },
        "rise-in": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "pulse-ring": {
          "0%, 100%": { opacity: "0.45" },
          "50%": { opacity: "1" },
        },
        // ── landing page ────────────────────────────────────────────────
        // Long, slow and low-contrast on purpose. Motion on a marketing page
        // should make the product legible, not compete with it.
        "fade-up": {
          from: { opacity: "0", transform: "translateY(14px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
        "slide-in-left": {
          from: { opacity: "0", transform: "translateX(-10px)" },
          to: { opacity: "1", transform: "translateX(0)" },
        },
        "scale-in": {
          from: { opacity: "0", transform: "scale(0.96)" },
          to: { opacity: "1", transform: "scale(1)" },
        },
        drift: {
          "0%, 100%": { transform: "translate(0, 0) scale(1)" },
          "33%": { transform: "translate(3%, -4%) scale(1.06)" },
          "66%": { transform: "translate(-3%, 3%) scale(0.96)" },
        },
        scan: {
          "0%": { transform: "translateY(-100%)", opacity: "0" },
          "12%": { opacity: "1" },
          "88%": { opacity: "1" },
          "100%": { transform: "translateY(1100%)", opacity: "0" },
        },
        "grow-x": { from: { transform: "scaleX(0)" }, to: { transform: "scaleX(1)" } },
        blink: { "0%, 49%": { opacity: "1" }, "50%, 100%": { opacity: "0" } },
        "beam-down": {
          "0%": { transform: "translateY(-60%)", opacity: "0" },
          "40%, 60%": { opacity: "0.9" },
          "100%": { transform: "translateY(60%)", opacity: "0" },
        },
        "sheen": {
          "0%": { transform: "translateX(-120%)" },
          "100%": { transform: "translateX(220%)" },
        },
      },
      animation: {
        shimmer: "shimmer 1.6s ease-in-out infinite",
        "rise-in": "rise-in 260ms cubic-bezier(0.16,1,0.3,1) both",
        "pulse-ring": "pulse-ring 2.4s ease-in-out infinite",
        "fade-up": "fade-up 620ms cubic-bezier(0.16,1,0.3,1) both",
        "fade-in": "fade-in 700ms ease-out both",
        "slide-in-left": "slide-in-left 460ms cubic-bezier(0.16,1,0.3,1) both",
        "scale-in": "scale-in 420ms cubic-bezier(0.16,1,0.3,1) both",
        drift: "drift 22s ease-in-out infinite",
        "drift-slow": "drift 34s ease-in-out infinite reverse",
        scan: "scan 3.2s cubic-bezier(0.4,0,0.2,1) infinite",
        "grow-x": "grow-x 900ms cubic-bezier(0.16,1,0.3,1) both",
        blink: "blink 1.1s step-end infinite",
        "beam-down": "beam-down 2.6s ease-in-out infinite",
        sheen: "sheen 2.8s ease-in-out infinite",
      },
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      },
    },
  },
  plugins: [],
};

export default config;

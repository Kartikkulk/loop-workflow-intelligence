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
        good: { 500: "#10b981", 400: "#34d399" },
        warn: { 500: "#f59e0b", 400: "#fbbf24" },
        bad: { 500: "#ef4444", 400: "#f87171" },
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

import type { Metadata } from "next";
import localFont from "next/font/local";
import { AuthGuard } from "@/components/auth-guard";
import { Nav } from "@/components/nav";
import { Providers } from "@/components/providers";
import "./globals.css";

/**
 * Inter, served from this repository rather than fetched from Google.
 *
 * `next/font/google` downloads the face at *build* time, which quietly makes
 * every build and every `next dev` start depend on reaching
 * fonts.googleapis.com. When DNS failed here the dev server took seventeen
 * minutes to become ready and the first page took twenty-seven to compile,
 * with one line in the log to explain it. On a hackathon network, or for a
 * judge building offline, that is a demo lost to something that has nothing to
 * do with the product.
 *
 * One variable file covers 400-600 — Google serves the same woff2 for all
 * three weights, so shipping three copies would have been 96KB of duplication.
 */
const inter = localFont({
  src: "./fonts/Inter-variable.woff2",
  weight: "100 900",
  style: "normal",
  display: "swap",
  variable: "--font-inter",
  // Rendered before the face loads; sized to Inter so the swap does not shift
  // the layout.
  fallback: ["system-ui", "-apple-system", "Segoe UI", "sans-serif"],
});

export const metadata: Metadata = {
  title: "LOOP — Workflow Intelligence",
  description:
    "Finds the work your team repeats, turns it into automations, and makes each one earn the right to run.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={inter.variable}>
      <body className="min-h-screen font-sans antialiased">
        <Providers>
          <AuthGuard>
            <div className="flex min-h-screen">
              <Nav />
              <main className="min-w-0 flex-1">{children}</main>
            </div>
          </AuthGuard>
        </Providers>
      </body>
    </html>
  );
}

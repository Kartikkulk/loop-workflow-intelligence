/**
 * Assembles a loadable extension for each browser.
 *
 *   node collectors/build.mjs            # both
 *   node collectors/build.mjs chrome     # one
 *
 * Output goes to collectors/dist/<browser>/, which is what you point
 * "Load unpacked" at.
 *
 * Why a build step rather than two copies of the extension: the observing
 * logic is identical on Chrome and Edge — both are Chromium and both run MV3.
 * Two copies would mean every fix to content.js has to be made twice, and one
 * of them would eventually be forgotten. So the logic lives once in shared/,
 * and each browser folder holds only what genuinely differs.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SHARED = path.join(HERE, "shared");
const DIST = path.join(HERE, "dist");

const BROWSERS = ["chrome", "edge"];

/** Files every browser gets, copied verbatim from shared/. */
const SHARED_FILES = [
  "content.js",
  "background.js",
  "options.html",
  "options.js",
  "popup.html",
  "popup.js",
];

function build(browser) {
  const src = path.join(HERE, browser);
  if (!fs.existsSync(src)) {
    throw new Error(`no folder for '${browser}' — expected ${src}`);
  }

  const out = path.join(DIST, browser);
  fs.rmSync(out, { recursive: true, force: true });
  fs.mkdirSync(out, { recursive: true });

  for (const file of SHARED_FILES) {
    const from = path.join(SHARED, file);
    if (!fs.existsSync(from)) throw new Error(`shared/${file} is missing`);
    fs.copyFileSync(from, path.join(out, file));
  }

  // Anything in the browser folder is copied last, so a browser can override
  // a shared file simply by having its own copy of it.
  let overrides = 0;
  for (const entry of fs.readdirSync(src)) {
    fs.copyFileSync(path.join(src, entry), path.join(out, entry));
    if (SHARED_FILES.includes(entry)) overrides += 1;
  }

  const manifest = JSON.parse(fs.readFileSync(path.join(out, "manifest.json"), "utf8"));
  const count = fs.readdirSync(out).length;
  console.log(
    `  ${browser.padEnd(7)} → collectors/dist/${browser}  ` +
      `(${count} files, ${overrides} override${overrides === 1 ? "" : "s"}, ` +
      `manifest v${manifest.manifest_version})`,
  );
}

const requested = process.argv.slice(2);
const targets = requested.length ? requested : BROWSERS;
for (const browser of targets) build(browser);

console.log("");
console.log("Load unpacked:");
for (const browser of targets) {
  const url = browser === "edge" ? "edge://extensions" : "chrome://extensions";
  console.log(`  ${browser}: ${url} → Developer mode → Load unpacked → collectors/dist/${browser}`);
}

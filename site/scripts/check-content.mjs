// Content rules the built page must satisfy, or the build fails:
//   - no old command name (0011 C2): the string "qf " never appears
//   - no third-party origin in served HTML/CSS/JS (self-hosted assets, no tracking)
//   - the readable-before-JavaScript content is present in the HTML itself
//   - the disclaimer is on the page and backtested figures are labelled hypothetical
import { readdirSync, readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const dist = join(dirname(fileURLToPath(import.meta.url)), "..", "dist");
const html = readFileSync(join(dist, "index.html"), "utf8");
const assets = readdirSync(join(dist, "assets")).map((f) => readFileSync(join(dist, "assets", f), "utf8"));
const failures = [];

if (/\bqf /.test(html)) failures.push('the old command name "qf " appears in the page');
// Only *requests* count: tags that fetch (script, link stylesheet/preload/font, img, iframe) and
// runtime fetch/beacon calls. Library banners mention their homepages in comments; that is not a request.
const allowed = new Set(["ai-solutions-lab-llc.github.io"]);
const tagRequests = [...html.matchAll(/<(script|link|img|iframe|source)\b[^>]*\b(?:src|href)="(https?:\/\/[^"/]+)/gi)];
for (const m of tagRequests) {
  const tag = m[0].toLowerCase();
  if (m[1].toLowerCase() === "link" && !/rel="(stylesheet|preload|prefetch|modulepreload|icon)"/.test(tag)) continue;
  const origin = new URL(m[2]).hostname;
  if (!allowed.has(origin)) failures.push(`index.html: <${m[1]}> loads from ${origin}`);
}
for (const [i, text] of assets.entries()) {
  for (const m of text.matchAll(/(?:fetch|sendBeacon|XMLHttpRequest|importScripts|new Image)\s*\(\s*["'`](https?:\/\/[^"'`]+)/g)) {
    failures.push(`assets[${i}]: runtime request to ${m[1]}`);
  }
}
for (const needle of ["pip install sobres", "docker run", "github.com/AI-Solutions-Lab-LLC/sobres", "Not investment advice", "hypothetical", "<h1"]) {
  if (!html.includes(needle)) failures.push(`index.html lacks "${needle}"`);
}
if (failures.length) {
  for (const f of failures) console.error(`content: ${f}`);
  process.exit(1);
}
console.log("content: ok");

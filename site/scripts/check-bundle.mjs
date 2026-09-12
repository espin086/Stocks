// The initial JavaScript bundle must stay under 150 KB compressed; exceeding it fails the build.
import { readdirSync, readFileSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const BUDGET = 150 * 1024;
const dist = join(dirname(fileURLToPath(import.meta.url)), "..", "dist");
const html = readFileSync(join(dist, "index.html"), "utf8");
const eager = [...html.matchAll(/(?:src|href)="[^"]*\/assets\/([^"]+\.js)"/g)].map((m) => m[1]);
const initial = new Set(eager);
let total = 0;
for (const name of readdirSync(join(dist, "assets"))) {
  if (!name.endsWith(".js") || !initial.has(name)) continue;
  const size = gzipSync(readFileSync(join(dist, "assets", name))).length;
  total += size;
  console.log(`${name}: ${(size / 1024).toFixed(1)} KB gzip`);
}
console.log(`initial bundle: ${(total / 1024).toFixed(1)} KB gzip (budget ${BUDGET / 1024} KB)`);
if (total > BUDGET) {
  console.error("bundle budget exceeded");
  process.exit(1);
}

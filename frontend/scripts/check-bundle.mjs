// The initial JavaScript bundle must stay under 300 KB compressed; exceeding it fails the build.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { join } from "node:path";

const BUDGET = 300 * 1024;
const dir = join(process.cwd(), "..", "src", "sobres", "api", "static", "assets");
const html = readFileSync(join(dir, "..", "index.html"), "utf8");
// Only scripts referenced from index.html load eagerly; code-split chunks load on demand.
const eager = [...html.matchAll(/src="\/assets\/([^"]+\.js)"/g)].map((m) => m[1]);
const modulepreload = [...html.matchAll(/href="\/assets\/([^"]+\.js)"/g)].map((m) => m[1]);
const initial = new Set([...eager, ...modulepreload]);
let total = 0;
for (const name of readdirSync(dir)) {
  if (!name.endsWith(".js") || !initial.has(name)) continue;
  const size = gzipSync(readFileSync(join(dir, name))).length;
  total += size;
  console.log(`${name}: ${(size / 1024).toFixed(1)} KB gzip`);
}
console.log(`initial bundle: ${(total / 1024).toFixed(1)} KB gzip (budget ${BUDGET / 1024} KB)`);
if (total > BUDGET) {
  console.error("bundle budget exceeded");
  process.exit(1);
}
statSync(dir);

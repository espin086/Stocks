// Fail when the committed generated client differs from a fresh generation.
import { readFileSync, unlinkSync } from "node:fs";

const committed = readFileSync("src/api/schema.d.ts", "utf8");
const fresh = readFileSync("src/api/schema.generated.tmp.d.ts", "utf8");
unlinkSync("src/api/schema.generated.tmp.d.ts");
if (committed !== fresh) {
  console.error("src/api/schema.d.ts is stale: run `npm run generate:client` and commit the result");
  process.exit(1);
}
console.log("generated client is current");

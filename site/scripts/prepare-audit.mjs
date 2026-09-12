// Lighthouse serves a directory at the site root, but the page is built for /sobres/ (GitHub
// Pages project path). Stage dist/ under lhci-root/sobres so the audit loads the real URLs.
import { cpSync, mkdirSync, rmSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const site = join(dirname(fileURLToPath(import.meta.url)), "..");
const root = join(site, "lhci-root");
rmSync(root, { recursive: true, force: true });
mkdirSync(root, { recursive: true });
cpSync(join(site, "dist"), join(root, "sobres"), { recursive: true });
console.log("audit root staged at lhci-root/sobres");

// Build-time facts from the repository: the version and the install commands.
// The build fails if the version cannot be resolved, so the page cannot go stale silently.
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repo = join(here, "..", "..");
const about = readFileSync(join(repo, "src", "sobres", "__about__.py"), "utf8");
const match = about.match(/__version__\s*=\s*"([^"]+)"/);
if (!match) {
  console.error("generate: could not resolve __version__ from src/sobres/__about__.py");
  process.exit(1);
}
const version = match[1];
const image = "aisolutionslab/sobres";
const generated = {
  version,
  install: {
    pip: "pip install sobres",
    pipWeb: 'pip install "sobres[web]"',
    docker: `docker run -p 8787:8787 -v sobres:/data ${image}:${version} serve --host 0.0.0.0`,
  },
  repository: "https://github.com/AI-Solutions-Lab-LLC/sobres",
  generatedAt: new Date().toISOString(),
};
mkdirSync(join(here, "..", "src"), { recursive: true });
writeFileSync(join(here, "..", "src", "generated.json"), JSON.stringify(generated, null, 2) + "\n");
console.log(`generate: sobres ${version}`);

import type { Provenance as Prov } from "@/api/client";

/** The estimators, window, currency and notes the CLI prints in its header. */
export function ProvenanceBlock({ provenance, extra = [] }: { provenance?: Prov; extra?: string[] }) {
  if (!provenance && extra.length === 0) return null;
  const lines: string[] = [...extra];
  if (provenance?.provider) lines.push(`source: ${provenance.provider}${provenance.field ? ` (${provenance.field})` : ""}`);
  if (provenance?.return_kind) lines.push(`prices are ${provenance.return_kind}`);
  if (provenance?.currency) {
    lines.push(
      typeof provenance.currency === "string"
        ? `currency: ${provenance.currency}`
        : `currency: mixed (${Object.entries(provenance.currency)
            .map(([k, v]) => `${k}=${v}`)
            .join(", ")})`,
    );
  }
  if (provenance?.start || provenance?.end) lines.push(`window: ${provenance.start ?? "…"} → ${provenance.end ?? "…"}`);
  if (provenance?.cache) lines.push(`cache: ${provenance.cache}`);
  for (const flag of provenance?.flags ?? []) lines.push(`flag: ${flag.symbol} ${flag.date} ${flag.detail}`);
  for (const note of provenance?.notes ?? []) lines.push(note);
  const inSample = lines.some((l) => l.startsWith("in-sample"));
  return (
    <div className="mb-3 space-y-0.5 text-xs text-fg-muted">
      {inSample && (
        <span className="mr-2 inline-block rounded bg-warn px-1.5 py-0.5 text-[10px] font-semibold uppercase text-black">
          in-sample
        </span>
      )}
      {lines.map((line, i) => (
        <div key={i}>{line}</div>
      ))}
    </div>
  );
}

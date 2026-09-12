export const DISCLAIMER = "For research and education only. Not investment advice.";

/** Present on every analysis result; not dismissible in a way that persists. */
export function Disclaimer() {
  return (
    <p role="note" className="mt-3 border-t border-border pt-2 text-xs text-fg-muted">
      {DISCLAIMER}
    </p>
  );
}

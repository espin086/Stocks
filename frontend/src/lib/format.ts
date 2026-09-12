export function formatCell(value: unknown, kind: "price" | "return" | "weight" | "text" | "auto" = "auto"): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "number") {
    if (Number.isInteger(value) && kind === "auto") return value.toLocaleString();
    const digits = kind === "price" ? 2 : 4;
    return value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function toCsv(columns: string[], rows: Record<string, unknown>[]): string {
  const escape = (v: unknown) => {
    const text = v === null || v === undefined ? "" : String(v);
    return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  return [columns.join(","), ...rows.map((r) => columns.map((c) => escape(r[c])).join(","))].join("\n") + "\n";
}

export function download(name: string, text: string, type = "text/csv"): void {
  const blob = new Blob([text], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

/** The equivalent `sobres` command line for a filled-in form. */
export function commandLine(name: string, params: Record<string, unknown>, positional: string[]): string {
  const parts = ["sobres", ...name.split(".")];
  for (const key of positional) {
    const value = params[key];
    if (Array.isArray(value)) parts.push(...value.map(String));
    else if (value !== undefined && value !== null && value !== "") parts.push(String(value));
  }
  for (const [key, value] of Object.entries(params)) {
    if (positional.includes(key) || value === undefined || value === null || value === "") continue;
    const flag = `--${key.replace(/_/g, "-")}`;
    if (typeof value === "boolean") {
      if (value) parts.push(flag);
    } else if (Array.isArray(value)) {
      if (value.length) parts.push(flag, ...value.map(String));
    } else {
      parts.push(flag, String(value));
    }
  }
  return parts.join(" ");
}

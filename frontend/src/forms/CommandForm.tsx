import { useMemo, useState } from "react";
import type { CommandSchema, ParamSchema } from "@/api/client";
import { commandLine } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";

export type FormValues = Record<string, unknown>;

/** The values a form starts with: every default from the registry, visible, never hidden. */
export function initialValues(schema: CommandSchema): FormValues {
  const values: FormValues = {};
  for (const p of schema.params) {
    values[p.name] = p.multiple ? (Array.isArray(p.default) ? p.default : []) : (p.default ?? (p.type === "bool" ? false : ""));
  }
  return values;
}

/** Only the values that differ from an omitted parameter go to the API and the command line. */
export function bodyOf(schema: CommandSchema, values: FormValues): FormValues {
  const body: FormValues = {};
  for (const p of schema.params) {
    const v = values[p.name];
    if (p.multiple) {
      const list = Array.isArray(v) ? v : String(v ?? "").split(/[\s,]+/).filter(Boolean);
      if (list.length) body[p.name] = p.type === "list[float]" ? list.map(Number) : list;
    } else if (p.type === "bool") {
      if (v) body[p.name] = true;
    } else if (v !== "" && v !== null && v !== undefined) {
      body[p.name] = p.type === "int" ? Number(v) : p.type === "float" ? Number(v) : v;
    }
  }
  return body;
}

function Field({ param, value, onChange }: { param: ParamSchema; value: unknown; onChange: (v: unknown) => void }) {
  const id = `f-${param.name}`;
  const label = (
    <label htmlFor={id} className="block text-sm font-medium">
      {param.name.replace(/_/g, " ")}
      {param.required && <span className="text-fail"> *</span>}
    </label>
  );
  const hint = <p className="text-xs text-fg-muted">{param.help}</p>;
  if (param.type === "bool") {
    return (
      <div className="flex items-center justify-between gap-3 py-1">
        <div>
          {label}
          {hint}
        </div>
        <Switch id={id} checked={Boolean(value)} onCheckedChange={onChange} />
      </div>
    );
  }
  if (param.choices.length) {
    return (
      <div>
        {label}
        <select id={id} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} className="w-full rounded border border-border bg-bg px-2 py-1.5 text-sm">
          {!param.required && <option value="">(none)</option>}
          {param.choices.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        {hint}
      </div>
    );
  }
  const isList = param.multiple;
  const text = isList && Array.isArray(value) ? value.join(" ") : String(value ?? "");
  return (
    <div>
      {label}
      <input
        id={id}
        type={param.type === "int" || param.type === "float" ? "number" : "text"}
        step={param.type === "float" ? "any" : undefined}
        value={text}
        placeholder={isList ? "space separated" : param.type.includes("date") ? "YYYY-MM-DD" : ""}
        onChange={(e) => onChange(isList ? e.target.value.split(/[\s,]+/).filter(Boolean) : e.target.value)}
        className="w-full rounded border border-border bg-bg px-2 py-1.5 text-sm"
      />
      {hint}
    </div>
  );
}

const DANGEROUS = new Set(["cache.clear", "portfolio.delete", "watchlist.delete", "run.delete", "db.repair"]);

export function CommandForm({
  schema,
  onSubmit,
  busy,
  initial,
}: {
  schema: CommandSchema;
  onSubmit: (body: FormValues) => void;
  busy: boolean;
  initial?: FormValues;
}) {
  const [values, setValues] = useState<FormValues>(() => ({ ...initialValues(schema), ...(initial ?? {}) }));
  const positional = useMemo(() => schema.params.filter((p) => p.positional).map((p) => p.name), [schema]);
  const body = useMemo(() => bodyOf(schema, values), [schema, values]);
  const line = useMemo(() => commandLine(schema.name, body, positional), [schema.name, body, positional]);
  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(body);
      }}
    >
      {schema.params.map((p) => (
        <Field key={p.name} param={p} value={values[p.name]} onChange={(v) => setValues((s) => ({ ...s, [p.name]: v }))} />
      ))}
      <div className="rounded border border-border bg-bg p-2 text-xs">
        <div className="mb-1 flex items-center justify-between text-fg-muted">
          <span>equivalent command</span>
          <button type="button" className="underline" onClick={() => void navigator.clipboard?.writeText(line)}>
            copy
          </button>
        </div>
        <code className="break-all">{line}</code>
      </div>
      <Button type="submit" disabled={busy} variant={DANGEROUS.has(schema.name) ? "danger" : "primary"}>
        {busy ? "Running…" : schema.long_running ? "Run as job" : "Run"}
      </Button>
    </form>
  );
}

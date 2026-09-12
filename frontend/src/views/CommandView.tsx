import { useState } from "react";
import { useLocation, useParams } from "react-router-dom";
import { motion } from "motion/react";
import { api, ApiFailure, streamJob, type JobEvent, type ResultPayload } from "@/api/client";
import { CommandForm, type FormValues } from "@/forms/CommandForm";
import { JobProgress } from "@/components/JobProgress";
import { Card, CardTitle } from "@/components/ui/card";
import { prefersReducedMotion } from "@/theme/ThemeProvider";
import { useCommands } from "./HomeView";
import { ResultView } from "./ResultView";

/** A form generated from the registry, its equivalent command line, and the result. */
export function CommandView() {
  const { name = "" } = useParams();
  const location = useLocation();
  const { data } = useCommands();
  const [result, setResult] = useState<ResultPayload | null>(null);
  const [job, setJob] = useState<JobEvent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const schema = data?.find((c) => c.name === name);
  if (!data) return <p>loading…</p>;
  if (!schema) return <p className="text-fail">no command named {name}</p>;
  const prefill = (location.state as { params?: FormValues } | null)?.params;

  const run = async (body: FormValues) => {
    setBusy(true);
    setError(null);
    setResult(null);
    setJob(null);
    try {
      if (schema.long_running) {
        const queued = await api.post<JobEvent>(schema.route, body);
        setJob(queued); // queued within the request round-trip: immediate feedback
        const final = await streamJob(queued.job_id, setJob);
        if (final.state === "succeeded" && final.result) setResult(final.result);
      } else {
        setResult(await api.post<ResultPayload>(schema.route, body));
      }
    } catch (e) {
      const failure = e as ApiFailure;
      setError(failure.body ? `${failure.body.error}${failure.body.hint ? ` — ${failure.body.hint}` : ""}` : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(280px,1fr)_2fr]">
      <Card>
        <CardTitle>{schema.name}</CardTitle>
        <p className="mb-3 text-sm text-fg-muted">{schema.help}</p>
        <CommandForm key={name} schema={schema} onSubmit={run} busy={busy} initial={prefill} />
      </Card>
      <Card>
        <CardTitle>result</CardTitle>
        {job && <JobProgress job={job} />}
        {error && <p className="text-sm text-fail">{error}</p>}
        {result && (
          <motion.div
            initial={prefersReducedMotion() ? false : { opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25 }}
          >
            <ResultView schema={schema} result={result} />
          </motion.div>
        )}
        {!result && !job && !error && <p className="text-sm text-fg-muted">fill the form and run — the equivalent CLI line updates live.</p>}
      </Card>
    </div>
  );
}

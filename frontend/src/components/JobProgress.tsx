import { Button } from "./ui/button";
import { api, type JobEvent } from "@/api/client";

/** Progress is real: it reflects the job stream, never a fake indeterminate bar. */
export function JobProgress({ job, onCancel }: { job: JobEvent; onCancel?: () => void }) {
  const percent = Math.round((job.progress ?? 0) * 100);
  return (
    <div className="my-3 rounded border border-border p-3" aria-live="polite">
      <div className="mb-1 flex items-center justify-between text-sm">
        <span>
          job <code>{job.job_id}</code> — {job.state}
          {job.message ? ` · ${job.message}` : ""}
        </span>
        {(job.state === "queued" || job.state === "running") && (
          <Button
            variant="ghost"
            onClick={() => {
              void api.post(`/api/v1/jobs/${job.job_id}/cancel`, {});
              onCancel?.();
            }}
          >
            Cancel
          </Button>
        )}
      </div>
      <div className="h-2 w-full overflow-hidden rounded bg-bg" role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>
        <div className="h-full bg-accent transition-[width]" style={{ width: `${percent}%` }} />
      </div>
      {job.error && (
        <p className="mt-2 text-sm text-fail">
          {job.error.error_class}: {job.error.error}
          {job.error.hint ? ` — ${job.error.hint}` : ""}
        </p>
      )}
    </div>
  );
}

import { useQuery } from "@tanstack/react-query";
import { api, type JobEvent } from "@/api/client";
import { Card, CardTitle } from "@/components/ui/card";
import { JobProgress } from "@/components/JobProgress";

/** Work outlives the page: navigating away never cancels a job. */
export function JobsView() {
  const { data } = useQuery({
    queryKey: ["jobs"],
    queryFn: () => api.get<{ jobs: JobEvent[] }>("/api/v1/jobs?limit=50"),
    refetchInterval: 2000,
  });
  return (
    <Card>
      <CardTitle>jobs</CardTitle>
      {(data?.jobs ?? []).map((j) => (
        <JobProgress key={j.job_id} job={j} />
      ))}
      {data && data.jobs.length === 0 && <p className="text-sm text-fg-muted">no jobs yet</p>}
    </Card>
  );
}

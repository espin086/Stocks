// A thin fetch wrapper over the generated OpenAPI types. Tokens travel as an
// httpOnly cookie set by /api/v1/auth/login — never in a URL.
import type { paths } from "./schema";

export type Paths = paths;
export type CommandRoute = Extract<keyof paths, `/api/v1/${string}`>;

export interface ApiError {
  error: string;
  hint?: string | null;
  error_class?: string;
  exit_code?: number;
  run_id?: string;
}

export class ApiFailure extends Error {
  constructor(
    public readonly status: number,
    public readonly body: ApiError,
  ) {
    super(body.error);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
    credentials: "same-origin",
  });
  if (response.status === 401) {
    window.dispatchEvent(new CustomEvent("sobres:unauthorized"));
  }
  const text = await response.text();
  const body = text ? (JSON.parse(text) as unknown) : null;
  if (!response.ok) {
    const err = (body ?? { error: response.statusText }) as ApiError;
    throw new ApiFailure(response.status, err);
  }
  return body as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body ?? {}) }),
};

// ---- registry shapes served by GET /api/v1/commands -------------------------
export interface ParamSchema {
  name: string;
  type: string;
  required: boolean;
  default: unknown;
  help: string;
  choices: string[];
  positional: boolean;
  multiple: boolean;
}

export interface CommandSchema {
  name: string;
  group: string | null;
  command: string;
  help: string;
  result: string;
  report: boolean;
  emits_data: boolean;
  long_running: boolean;
  route: string;
  params: ParamSchema[];
}

export interface Provenance {
  provider?: string | null;
  field?: string | null;
  return_kind?: string | null;
  currency?: string | Record<string, string> | null;
  start?: string | null;
  end?: string | null;
  cache?: string | null;
  fetched_at?: string | null;
  flags?: Record<string, string>[];
  notes?: string[];
}

export interface ResultPayload {
  provenance?: Provenance;
  columns?: string[];
  rows?: Record<string, unknown>[];
  [key: string]: unknown;
}

export interface JobEvent {
  job_id: string;
  state: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  progress: number;
  command: string;
  message?: string;
  result?: ResultPayload | null;
  error?: ApiError | null;
  url?: string;
}

export const TERMINAL = new Set(["succeeded", "failed", "cancelled"]);

/** Subscribe to a job's SSE stream; resolves with the terminal event. */
export function streamJob(jobId: string, onEvent: (e: JobEvent) => void): Promise<JobEvent> {
  return new Promise((resolve, reject) => {
    const source = new EventSource(`/api/v1/jobs/${jobId}/events`);
    source.addEventListener("job", (message) => {
      const event = JSON.parse((message as MessageEvent).data) as JobEvent;
      onEvent(event);
      if (TERMINAL.has(event.state)) {
        source.close();
        resolve(event);
      }
    });
    source.onerror = () => {
      // The browser reconnects on its own; a closed stream after a terminal state is normal.
      if (source.readyState === EventSource.CLOSED) {
        api.get<JobEvent>(`/api/v1/jobs/${jobId}`).then(resolve).catch(reject);
      }
    };
  });
}

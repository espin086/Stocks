"""Long-running work as persisted jobs with a single in-process worker.

No HTTP request waits on a computation: the route persists a job record and
returns its id; one worker drains the queue. Progress comes from the core
function's optional callback through ``Context.report_progress``; the runner
turns it into a row update and an event for SSE subscribers. Cancellation is
checked at those same checkpoints. The record lives in 0003's job repository,
so a job survives a restart and a page reload.
"""

from __future__ import annotations

import queue
import threading
import traceback
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from sobres.cli.context import Context
from sobres.config import Config
from sobres.core.errors import JobCancelledError, SobresError
from sobres.data.storage.base import TERMINAL_JOB_STATES, JobRecord, Storage
from sobres.observability import get_logger, new_run_id, span
from sobres.registry import Command, get_command, validate_params

Event = dict[str, Any]


def job_event(job: JobRecord, message: str | None = None) -> Event:
    event: Event = {
        "job_id": job.id,
        "state": job.state,
        "progress": job.progress,
        "command": job.command,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }
    if message is not None:
        event["message"] = message
    if job.state in TERMINAL_JOB_STATES:
        event["result"] = job.result
        event["error"] = job.error
    return event


class JobRunner:
    """One worker thread; ``submit`` enqueues, ``subscribe`` streams events."""

    def __init__(
        self,
        storage: Storage,
        config: Config,
        environ: Mapping[str, str],
        *,
        sources: dict[str, Any] | None = None,
    ) -> None:
        self._storage = storage
        self._config = config
        self._environ = dict(environ)
        self._sources = sources or {}
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._cancel: set[str] = set()
        self._subscribers: dict[str, list[queue.Queue[Event]]] = {}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._log = get_logger("sobres.api.jobs")

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self._thread is not None:
            return
        self.recover_orphans("the previous process exited before this job finished")
        self._thread = threading.Thread(target=self._loop, name="sobres-jobs", daemon=True)
        self._thread.start()

    def stop(self, grace: float = 8.0) -> None:
        """Ask a running job to stop at its next checkpoint, then record whatever is left."""
        self._stop.set()
        self._wake.set()
        with self._lock:
            for job in self._storage.jobs.list(limit=100, state="running"):
                self._cancel.add(job.id)
        if self._thread is not None:
            self._thread.join(timeout=grace)
            self._thread = None
        self.recover_orphans("the server shut down before this job finished")

    def recover_orphans(self, reason: str) -> int:
        """Mark every job still ``running`` as failed with ``reason``; returns how many."""
        count = 0
        for job in self._storage.jobs.list(limit=100, state="running"):
            final = self._storage.jobs.update(
                job.id,
                state="failed",
                error={
                    "message": reason,
                    "hint": "submit the command again",
                    "exit_code": 1,
                    "error_class": "Interrupted",
                },
            )
            self._publish(job_event(final, reason))
            count += 1
        return count

    def _loop(self) -> None:
        while not self._stop.is_set():
            job = self._storage.jobs.next_queued()
            if job is None:
                self._wake.wait(0.5)
                self._wake.clear()
                continue
            self.run_job(job)

    # ------------------------------------------------------------- submission
    def submit(
        self,
        cmd: Command,
        params: dict[str, Any],
        *,
        run_id: str | None = None,
        trace_context: dict[str, Any] | None = None,
    ) -> JobRecord:
        job = self._storage.jobs.create(
            JobRecord(
                id=uuid.uuid4().hex[:12],
                command=cmd.name,
                params=params,
                run_id=run_id,
                trace_context=trace_context,
            )
        )
        self._wake.set()
        return job

    def cancel(self, job_id: str) -> JobRecord | None:
        job = self._storage.jobs.get(job_id)
        if job is None:
            return None
        if job.state == "queued":
            job = self._storage.jobs.update(job_id, state="cancelled")
            self._publish(job_event(job, "cancelled before it started"))
            return job
        if job.state == "running":
            with self._lock:
                self._cancel.add(job_id)
        return job

    def run_pending(self) -> int:
        """Drain the queue on the calling thread (tests, the CLI). Returns jobs run."""
        count = 0
        while (job := self._storage.jobs.next_queued()) is not None:
            self.run_job(job)
            count += 1
        return count

    # --------------------------------------------------------------- events
    def subscribe(self, job_id: str) -> queue.Queue[Event]:
        q: queue.Queue[Event] = queue.Queue()
        with self._lock:
            self._subscribers.setdefault(job_id, []).append(q)
        return q

    def unsubscribe(self, job_id: str, q: queue.Queue[Event]) -> None:
        with self._lock:
            subs = self._subscribers.get(job_id, [])
            if q in subs:
                subs.remove(q)

    def _publish(self, event: Event) -> None:
        with self._lock:
            subs = list(self._subscribers.get(event["job_id"], []))
        for q in subs:
            q.put(event)

    # --------------------------------------------------------------- execution
    def run_job(self, job: JobRecord) -> JobRecord:
        rid = job.run_id or new_run_id()
        new_run_id()
        import structlog

        structlog.contextvars.bind_contextvars(run_id=rid, job_id=job.id)
        cmd = get_command(job.command)
        job = self._storage.jobs.update(job.id, state="running", progress=0.0)
        self._publish(job_event(job, "started"))

        def progress(fraction: float, message: str) -> None:
            updated = self._storage.jobs.update(job.id, progress=float(fraction))
            self._publish(job_event(updated, message))

        def cancel_requested() -> bool:
            with self._lock:
                return job.id in self._cancel

        ctx = Context(
            config=self._config,
            environ=self._environ,
            interactive=False,
            sources=dict(self._sources),
            surface="job",
            progress=progress,
            cancel_requested=cancel_requested,
            _storage=self._storage,
        )
        carrier = dict(job.trace_context or {})
        final: JobRecord
        with span(f"job.{cmd.name}", {"job_id": job.id, "command": cmd.name}, carrier=carrier):
            try:
                params = validate_params(cmd, dict(job.params))
                result = cmd.handler(params, ctx)
                if getattr(params, "save_run", False):
                    from sobres.cli.main import record_run

                    record_run(cmd, params, result, ctx)
                payload = result.payload()
                final = self._storage.jobs.update(
                    job.id, state="succeeded", progress=1.0, result=payload
                )
                self._log.info("job.succeeded", job_id=job.id, command=cmd.name)
            except JobCancelledError:
                final = self._storage.jobs.update(job.id, state="cancelled")
                self._log.info("job.cancelled", job_id=job.id)
            except SobresError as exc:
                final = self._storage.jobs.update(
                    job.id,
                    state="failed",
                    error={
                        "message": exc.message,
                        "hint": exc.hint,
                        "exit_code": exc.exit_code,
                        "error_class": type(exc).__name__,
                    },
                )
                self._log.warning("job.failed", job_id=job.id, error=str(exc))
            except Exception as exc:
                final = self._storage.jobs.update(
                    job.id,
                    state="failed",
                    error={
                        "message": f"internal error ({type(exc).__name__})",
                        "hint": f"rerun with --debug and report the run id {rid}",
                        "exit_code": 1,
                        "error_class": "InternalError",
                    },
                )
                self._log.error("job.crashed", job_id=job.id, traceback=traceback.format_exc())
        with self._lock:
            self._cancel.discard(job.id)
        self._publish(job_event(final, "finished"))
        structlog.contextvars.unbind_contextvars("job_id")
        return final


def utc_now() -> datetime:
    return datetime.now(UTC)


ProgressCallback = Callable[[float, str], None]

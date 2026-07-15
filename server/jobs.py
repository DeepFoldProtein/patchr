"""Job state and lifecycle: the in-memory + file-backed job store, the
cross-replica status/queue helpers, the GPU job queue and its worker, and the
Boltz progress-tracking callback. Shared by server.py and the pipeline code."""

import asyncio
import logging
from concurrent.futures import Future
from datetime import datetime
from typing import Callable, Optional

from fastapi import HTTPException
from pytorch_lightning.callbacks import Callback

from server.config import GPU_QUEUE_MAX, WORK_DIR
from server.models import JobStatus

logger = logging.getLogger(__name__)

# This replica's job store + SSE progress streams.
jobs_db: dict = {}
progress_streams: dict = {}

# GPU job queue — created in server.startup_event (needs a running event loop).
gpu_job_queue = None      # asyncio.Queue | None
gpu_worker_task = None    # asyncio.Task | None


def _persist_job(job_id: str) -> None:
    """Write the job record to its dir under WORK_DIR so that a *second* replica
    (e.g. a per-GPU instance sharing WORK_DIR behind a round-robin balancer) can
    serve status/poll for a job it did not itself submit. Atomic, best-effort."""
    rec = jobs_db.get(job_id)
    if rec is None:
        return
    try:
        import json as _json
        d = WORK_DIR / job_id
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / "_status.json.tmp"
        tmp.write_text(_json.dumps(rec, default=str))
        tmp.replace(d / "_status.json")
    except Exception:
        pass


def _refresh_job(job_id: str) -> bool:
    """Make ``jobs_db[job_id]`` reflect the on-disk record. The instance that owns
    the job persists on every update, so re-reading the file lets any instance
    return current status for jobs submitted elsewhere. Returns True if known."""
    try:
        f = WORK_DIR / job_id / "_status.json"
        if f.is_file():
            import json as _json
            jobs_db[job_id] = _json.loads(f.read_text())
    except Exception:
        pass
    return job_id in jobs_db


def _scan_gpu_queue() -> tuple[int, list]:
    """Aggregate GPU-queue state across ALL replicas from the file-backed job
    records under WORK_DIR (each per-GPU instance persists _status.json there).

    A single replica's in-memory ``_gpu_job_queue`` only sees its own jobs, so on
    the round-robin LB deployment it cannot report the true system queue. Reading
    the shared records makes any replica able to answer for the whole cluster.

    Returns ``(running, queued)`` where ``running`` is the number of jobs executing
    on a GPU right now (status running_prediction) and ``queued`` is a time-ordered
    list of ``(queue_submitted_at, job_id)`` for jobs waiting for a GPU."""
    import json as _json
    running = 0
    queued: list = []
    try:
        for d in WORK_DIR.iterdir():
            if not d.is_dir():
                continue
            f = d / "_status.json"
            if not f.is_file():
                continue
            try:
                rec = _json.loads(f.read_text())
            except Exception:
                continue
            st = rec.get("status")
            if st == JobStatus.RUNNING_PREDICTION:
                running += 1
            elif st == JobStatus.PENDING and rec.get("queue_submitted_at"):
                queued.append((rec.get("queue_submitted_at") or "", rec.get("job_id") or d.name))
    except Exception:
        pass
    queued.sort()
    return running, queued


def _load_all_jobs() -> list:
    """Return every job across ALL replicas by reading the shared file-backed
    _status.json records under WORK_DIR, merged with this replica's in-memory
    jobs_db (for jobs not yet persisted). The list endpoint must NOT rely on the
    local jobs_db alone: behind the round-robin LB each replica only holds the
    jobs it created, and its copies of jobs updated elsewhere go stale."""
    import json as _json
    seen: dict = {}
    try:
        for d in WORK_DIR.iterdir():
            if not d.is_dir():
                continue
            f = d / "_status.json"
            if not f.is_file():
                continue
            try:
                rec = _json.loads(f.read_text())
            except Exception:
                continue
            seen[rec.get("job_id") or d.name] = rec
    except Exception:
        pass
    for jid, rec in jobs_db.items():
        seen.setdefault(jid, rec)
    return list(seen.values())


def _job_queue_view(job_id: str, running: int, queued: list) -> dict:
    """Build the per-job queue view (state + 1-based position) from a scan."""
    order = [jid for _, jid in queued]
    if job_id in order:
        pos = order.index(job_id) + 1
        return {"job_id": job_id, "state": "queued", "position": pos, "ahead": pos - 1}
    _refresh_job(job_id)
    st = jobs_db.get(job_id, {}).get("status")
    if st == JobStatus.RUNNING_PREDICTION:
        return {"job_id": job_id, "state": "running", "position": 0, "ahead": 0}
    if st in (JobStatus.COMPLETED, JobStatus.FAILED):
        return {"job_id": job_id, "state": st, "position": 0, "ahead": 0}
    if st is not None:
        # e.g. generating_template / freshly-pending (not yet on the GPU queue)
        return {"job_id": job_id, "state": st, "position": None, "ahead": None}
    return {"job_id": job_id, "state": "unknown", "position": None, "ahead": None}


def update_job_status(
    job_id: str,
    status: JobStatus,
    error: Optional[str] = None,
    **kwargs,
):
    if job_id not in jobs_db:
        return
    jobs_db[job_id]["status"] = status
    jobs_db[job_id]["updated_at"] = datetime.now().isoformat()
    if error:
        jobs_db[job_id]["error"] = error
    for key, value in kwargs.items():
        jobs_db[job_id][key] = value
    _persist_job(job_id)


class ProgressTracker(Callback):
    """Custom callback to track prediction progress."""

    def __init__(self, job_id: str, event_loop=None):
        super().__init__()
        self.job_id = job_id
        self.total_batches = 0
        self.current_batch = 0
        self.event_loop = event_loop
        self.base_progress = 0
        self.diffusion_progress = 0

    def on_predict_start(self, trainer, pl_module):
        self._emit_progress("Prediction started", 0)

    def on_predict_batch_start(self, trainer, pl_module, batch, batch_idx, dataloader_idx=0):
        self.current_batch = batch_idx
        if hasattr(trainer, "num_predict_batches"):
            self.total_batches = trainer.num_predict_batches[0]
        self.base_progress = 0
        self.diffusion_progress = 0
        progress = 0
        if self.total_batches > 0:
            progress = int((self.current_batch / self.total_batches) * 100)
        self._emit_progress(
            f"Processing batch {self.current_batch + 1}/{self.total_batches or '?'}",
            progress,
        )

    def on_predict_batch_end(self, trainer, pl_module, outputs, batch, batch_idx, dataloader_idx=0):
        self.current_batch = batch_idx + 1
        if hasattr(trainer, "num_predict_batches"):
            self.total_batches = trainer.num_predict_batches[0]
        progress = 100
        if self.total_batches > 0:
            progress = int((self.current_batch / self.total_batches) * 100)
        self._emit_progress(
            f"Completed batch {self.current_batch}/{self.total_batches or '?'}",
            progress,
        )

    def on_predict_end(self, trainer, pl_module):
        self._emit_progress("Prediction completed", 100)

    def update_base_progress(self, message: str, percentage: int):
        self.base_progress = min(percentage, 40)
        total_progress = self.base_progress + self.diffusion_progress
        self._emit_progress(message, total_progress)

    def update_diffusion_progress(self, message: str, step: int, total_steps: int):
        if total_steps > 0:
            diffusion_percentage = int((step / total_steps) * 60)
            self.diffusion_progress = diffusion_percentage
            total_progress = self.base_progress + self.diffusion_progress
            self._emit_progress(message, total_progress)

    def _emit_progress(self, message: str, percentage: int):
        update_job_status(
            self.job_id,
            JobStatus.RUNNING_PREDICTION,
            progress=f"{message} ({percentage}%)",
        )
        if self.job_id in progress_streams and self.event_loop:
            try:
                queue = progress_streams[self.job_id]
                if self.event_loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self._put_progress(queue, message, percentage),
                        self.event_loop,
                    )
            except Exception:
                pass

    async def _put_progress(self, queue: asyncio.Queue, message: str, percentage: int):
        try:
            await queue.put(
                {
                    "message": message,
                    "percentage": percentage,
                    "timestamp": datetime.now().isoformat(),
                }
            )
        except Exception:
            pass


async def _gpu_worker():
    """Background coroutine that processes GPU jobs sequentially."""
    while True:
        job_id, fn, future = await gpu_job_queue.get()
        try:
            logger.info("[GPU-Queue] Starting job %s  (queue depth: %d)", job_id, gpu_job_queue.qsize())
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, fn)
            future.set_result(result)
        except Exception as exc:
            future.set_exception(exc)
        finally:
            gpu_job_queue.task_done()
            logger.info("[GPU-Queue] Finished job %s  (queue depth: %d)", job_id, gpu_job_queue.qsize())


async def submit_gpu_job(job_id: str, fn: Callable, *, update_queued: bool = True) -> Future:
    """Submit a synchronous callable to the GPU job queue.

    Returns a Future that resolves when the job finishes.
    Raises HTTPException(503) if the queue is full.
    """
    future: Future = Future()
    try:
        gpu_job_queue.put_nowait((job_id, fn, future))
    except asyncio.QueueFull:
        raise HTTPException(
            status_code=503,
            detail=f"GPU job queue is full ({GPU_QUEUE_MAX} pending). Try again later.",
        )
    if update_queued:
        depth = gpu_job_queue.qsize()
        # queue_submitted_at is the ordering key used to compute a system-wide,
        # cross-replica queue position (see _scan_gpu_queue / queue_status). It is
        # the moment the job entered a GPU worker queue — distinct from created_at
        # (job creation, often earlier, during template generation).
        update_job_status(
            job_id,
            JobStatus.PENDING,
            progress=f"Queued (position {depth}/{GPU_QUEUE_MAX})",
            queue_submitted_at=datetime.now().isoformat(),
        )
    return future

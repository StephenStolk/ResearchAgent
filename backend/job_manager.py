from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from backend.models import ResearchPacket

@dataclass
class JobRuntime:
    job_id: str
    status: str = "queued"
    current_stage: str | None = None
    progress: float = 0.0
    error: str | None = None
    events: asyncio.Queue[dict[str, Any]] = field(
        default_factory=asyncio.Queue
    )
    
    task: asyncio.Task | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    
class JobManager:
    """Manages the lifecycle of research jobs, including queuing, execution, and status tracking."""
    
    def __init__(self):
        self._jobs: dict[str, JobRuntime] = {}
        self._jobs_lock = threading.Lock()
    
    def create(self, job_id: str) -> JobRuntime:
        runtime = JobRuntime(job_id=job_id)
        
        with self._jobs_lock:
            self._jobs[job_id] = runtime
            
        return runtime
    
    def get(self, job_id: str) -> JobRuntime | None:
        with self._jobs_lock:
            return self._jobs.get(job_id)
        
    def remove(self, job_id: str) -> None:
        with self._jobs_lock:
            self._jobs.pop(job_id, None)
    
    def update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        current_stage: str | None = None,
        progress: float | None = None,
        error: str | None = None,
    ) -> None:
        runtime = self.get(job_id)
        if runtime is None:
            raise ValueError(f"Job {job_id} not found")
        
        with runtime.lock:
            if status is not None:
                runtime.status = status
            if current_stage is not None:
                runtime.current_stage = current_stage
            if progress is not None:
                runtime.progress = progress
            if error is not None:
                runtime.error = error
         
        event = {
            "type": "progress",
            "job_id": job_id,
            "status": runtime.status,
            "current_stage": runtime.current_stage,
            "progress": runtime.progress,
            "error": runtime.error,
        }       
        self._publish_threadsafe(runtime, event)
        
    def publish(
        self,
        job_id: str,
        event_type: str,
        **payload: Any,
    ) -> None:
        runtime = self.get(job_id)
        
        if runtime is None:
            return
        
        event = {
            "type": event_type,
            "job_id": job_id,
            **payload,
        }
        
        self._publish_threadsafe(runtime, event)
        
    def _publish_threadsafe(
        self, 
        runtime: JobRuntime,
        event: dict[str, Any],
    ) -> None:
        """
        Queue an event safely from either the async event loop or a worker thread. This ensures that the event is added to the asyncio.Queue without blocking.
        """
        try:
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(
                runtime.events.put_nowait, 
                event,
            )
        except RuntimeError:
            # No running event loop in this thread.
            #
            # The worker normally receives the event loop explicitly
            # through the async endpoint, so this branch is mostly
            # defensive.
            pass
    
    async def stream(
        self,
        job_id: str,
    ):
        """
        Async generator that yields events for a given job. This allows clients to listen for real-time updates on the job's progress.
        """
        runtime = self.get(job_id)
        
        if runtime is None:
            yield {
                "type": "error",
                "job_id": job_id,
                "error": f"Job {job_id} not found",
            }
            return

        while True:
            event = await runtime.events.get()
            yield event
            
            if event["type"] in (
                "completed",
                "failed",
                "cancelled",
            ):
                break
            
job_manager = JobManager()
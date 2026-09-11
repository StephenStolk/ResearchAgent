from __future__ import annotations

import asyncio
import json

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend import agents
from backend.job_manager import job_manager
from backend.pipeline import load_job, run_research


app = FastAPI(
    title="Research Agent API",
    version="0.2.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ResearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)


class AskRequest(BaseModel):
    job_id: str
    question: str = Field(min_length=1, max_length=2000)


class ScenarioRequest(BaseModel):
    job_id: str
    assumptions: list[str] | None = None


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "research-agent",
        "version": "0.2.0",
    }


@app.get("/")
def root():
    return {
        "message": "Research Agent API is running"
    }


async def _run_job(job_id: str, query: str) -> None:
    """
    Execute the existing synchronous research pipeline outside
    the FastAPI event loop.

    Later this becomes a real durable worker.
    """

    runtime = job_manager.get(job_id)

    if runtime is None:
        return

    def progress_callback(
        callback_job_id: str,
        stage: str,
        progress: float,
        state: str,
        error: str | None = None,
    ):
        if state == "running":
            job_manager.update(
                callback_job_id,
                status="running",
                current_stage=stage,
                progress=progress,
            )

            job_manager.publish(
                callback_job_id,
                "stage_started",
                stage=stage,
                progress=progress,
            )

        elif state == "completed":
            job_manager.update(
                callback_job_id,
                current_stage=stage,
                progress=progress,
            )

            job_manager.publish(
                callback_job_id,
                "stage_completed",
                stage=stage,
                progress=progress,
            )

        elif state == "failed":
            job_manager.update(
                callback_job_id,
                status="running",
                current_stage=stage,
                progress=progress,
            )

            job_manager.publish(
                callback_job_id,
                "stage_failed",
                stage=stage,
                progress=progress,
                error=error,
            )

    try:
        job_manager.update(
            job_id,
            status="running",
            progress=0.0,
        )

        job_manager.publish(
            job_id,
            "started",
            progress=0.0,
        )

        packet = await asyncio.to_thread(
            run_research,
            query,
            progress_callback,
            job_id,
        )

        job_manager.update(
            job_id,
            status="completed",
            current_stage="complete",
            progress=1.0,
        )

        job_manager.publish(
            job_id,
            "completed",
            progress=1.0,
            report_status=packet.status.value,
        )

    except asyncio.CancelledError:
        job_manager.update(
            job_id,
            status="cancelled",
        )

        job_manager.publish(
            job_id,
            "cancelled",
        )

        raise

    except Exception as exc:
        job_manager.update(
            job_id,
            status="failed",
            error=str(exc),
        )

        job_manager.publish(
            job_id,
            "failed",
            error=str(exc),
        )


@app.post("/research", status_code=202)
async def research(request: ResearchRequest):
    """
    Start research and immediately return a job id.
    The actual pipeline runs in the background.
    """

    query = request.query.strip()

    if not query:
        raise HTTPException(
            status_code=400,
            detail="query must not be empty",
        )

    from backend.models import ResearchPacket

    packet = ResearchPacket(topic=query)

    runtime = job_manager.create(packet.job_id)

    job_manager.publish(
        packet.job_id,
        "queued",
        progress=0.0,
    )

    runtime.task = asyncio.create_task(
        _run_job(
            packet.job_id,
            query,
        )
    )

    return {
        "job_id": packet.job_id,
        "status": "queued",
    }


@app.get("/research/{job_id}")
def get_research(job_id: str):
    packet = load_job(job_id)

    if packet is None:
        runtime = job_manager.get(job_id)

        if runtime is None:
            raise HTTPException(
                status_code=404,
                detail="job not found",
            )

        return {
            "job_id": job_id,
            "status": runtime.status,
            "stage": runtime.current_stage,
            "progress": runtime.progress,
            "error": runtime.error,
        }

    runtime = job_manager.get(job_id)

    response = packet.model_dump(mode="json")

    if runtime:
        response["_runtime"] = {
            "status": runtime.status,
            "stage": runtime.current_stage,
            "progress": runtime.progress,
            "error": runtime.error,
        }

    return response


@app.get("/research/{job_id}/events")
async def research_events(job_id: str):
    """
    Server-Sent Events endpoint.

    The frontend can keep this connection open while research runs.
    """

    runtime = job_manager.get(job_id)

    if runtime is None and load_job(job_id) is None:
        raise HTTPException(
            status_code=404,
            detail="job not found",
        )

    async def event_stream():
        if runtime is None:
            yield (
                "data: "
                + json.dumps(
                    {
                        "type": "completed",
                        "job_id": job_id,
                        "progress": 1.0,
                    }
                )
                + "\n\n"
            )
            return

        async for event in job_manager.stream(job_id):
            yield (
                "data: "
                + json.dumps(event)
                + "\n\n"
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/ask")
def ask(request: AskRequest):
    packet = load_job(request.job_id)

    if packet is None:
        raise HTTPException(
            status_code=404,
            detail="job not found",
        )

    call_counter = {
        "count": 0
    }

    return agents.answer_question(
        packet,
        request.question,
        call_counter,
    )


@app.post("/scenario")
def scenario(request: ScenarioRequest):
    packet = load_job(request.job_id)

    if packet is None:
        raise HTTPException(
            status_code=404,
            detail="job not found",
        )

    call_counter = {
        "count": 0
    }

    return agents.generate_scenario(
        packet,
        request.assumptions,
        call_counter,
    )


@app.get("/sources/{source_id}")
def get_source(
    source_id: str,
    job_id: str,
):
    packet = load_job(job_id)

    if packet is None:
        raise HTTPException(
            status_code=404,
            detail="job not found",
        )

    source = next(
        (
            source
            for source in packet.sources
            if source.id == source_id
        ),
        None,
    )

    if source is None:
        raise HTTPException(
            status_code=404,
            detail="source not found",
        )

    evidence = [
        evidence
        for evidence in packet.evidence
        if evidence.source_id == source_id
    ]

    return {
        "source": source.model_dump(mode="json"),
        "evidence": [
            item.model_dump(mode="json")
            for item in evidence
        ],
    }
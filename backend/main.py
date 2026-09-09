from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend import agents
from backend.pipeline import load_job, run_research, save_job

app = FastAPI(title="Research Agent API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://127.0.0.1:5173", "http://127.0.0.1:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ResearchRequest(BaseModel):
    query: str


class AskRequest(BaseModel):
    job_id: str
    question: str


class ScenarioRequest(BaseModel):
    job_id: str
    assumptions: list[str] | None = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"message": "Research Agent API is running"}


@app.post("/research")
def research(request: ResearchRequest):
    """Synchronous research endpoint. This will block until the research is complete and return the results.
    """
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="query must not be empty")
    packet = run_research(request.query)
    return packet.model_dump(mode="json")


@app.get("/research/{job_id}")
def get_research(job_id: str):
    packet = load_job(job_id)
    if packet is None:
        raise HTTPException(status_code=404, detail="job not found")
    return packet.model_dump(mode="json")


@app.post("/ask")
def ask(request: AskRequest):
    packet = load_job(request.job_id)
    if packet is None:
        raise HTTPException(status_code=404, detail="job not found")
    call_counter = {"count": 0}
    result = agents.answer_question(packet, request.question, call_counter)
    return result


@app.post("/scenario")
def scenario(request: ScenarioRequest):
    packet = load_job(request.job_id)
    if packet is None:
        raise HTTPException(status_code=404, detail="job not found")
    call_counter = {"count": 0}
    result = agents.generate_scenario(packet, request.assumptions, call_counter)
    return result


@app.get("/sources/{source_id}")
def get_source(source_id: str, job_id: str):
    packet = load_job(job_id)
    if packet is None:
        raise HTTPException(status_code=404, detail="job not found")
    source = next((s for s in packet.sources if s.id == source_id), None)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    evidence = [e for e in packet.evidence if e.source_id == source_id]
    return {"source": source.model_dump(mode="json"), "evidence": [e.model_dump(mode="json") for e in evidence]}

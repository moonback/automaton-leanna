import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import db, tools, memory, resources, improvements, agents
from .agent import run_agent
from .heartbeat import worker
from .config import PROVIDER, MODEL

heartbeat_task = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global heartbeat_task
    db.init()
    heartbeat_task = asyncio.create_task(worker())
    yield
    heartbeat_task.cancel()
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        pass

app = FastAPI(title="Automaton Local API", version="0.4.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173", "file://"],
                   allow_methods=["*"], allow_headers=["*"])

class RunRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=12000)

class MemoryRequest(BaseModel):
    content: str = Field(min_length=1, max_length=10000)
    tags: str = Field(default="", max_length=500)
    importance: int = Field(default=3, ge=1, le=5)

class HeartbeatRequest(BaseModel):
    enabled: bool | None = None
    interval_seconds: int | None = Field(default=None, ge=30, le=86400)
    prompt: str | None = Field(default=None, max_length=4000)

class ImprovementRequest(BaseModel):
    patch: str = Field(min_length=1, max_length=50000)

class TeamRequest(BaseModel):
    task: str = Field(min_length=1, max_length=12000)

@app.get("/health")
def health():
    return {"status": "ok", "version": "0.4.0"}

@app.get("/config")
def public_config():
    return {"provider": PROVIDER, "model": MODEL}

@app.get("/workspace")
def workspace():
    return {"files": tools.list_files()}

@app.get("/history")
def history():
    return {"messages": db.history(100)}

@app.post("/agent/run")
async def agent_run(req: RunRequest):
    try:
        return await run_agent(req.prompt)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@app.get("/memory")
def memory_search(q: str = "", limit: int = 20):
    return {"memories": memory.recall(q, limit)}

@app.post("/memory")
def memory_create(req: MemoryRequest):
    try:
        return memory.remember(req.content, req.tags, req.importance)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@app.delete("/memory/{memory_id}")
def memory_delete(memory_id: int):
    try:
        return memory.forget(memory_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

@app.get("/heartbeat")
def heartbeat_status():
    return {"config": db.get_heartbeat(), "runs": db.heartbeat_history(20)}

@app.put("/heartbeat")
def heartbeat_update(req: HeartbeatRequest):
    return {"config": db.set_heartbeat(req.enabled, req.interval_seconds, req.prompt)}

@app.get("/resources")
def resource_snapshot():
    return resources.snapshot()

@app.post("/agents/run")
async def agents_run(req: TeamRequest):
    try:
        return await agents.run_team(req.task)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@app.post("/improvements/apply")
def improvement_apply(req: ImprovementRequest):
    try:
        return improvements.validate_and_apply(req.patch)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

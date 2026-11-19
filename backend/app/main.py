import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import db, tools, memory, resources, improvements, agents, objectives
from .agent import run_agent
from .heartbeat import worker
from .tasks import worker as task_worker
from .config import PROVIDER, MODEL

heartbeat_task = None
task_worker_task = None
objective_worker_task = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global heartbeat_task, task_worker_task, objective_worker_task
    db.init()
    heartbeat_task = asyncio.create_task(worker())
    task_worker_task = asyncio.create_task(task_worker())
    objective_worker_task = asyncio.create_task(objectives.worker())
    yield
    objective_worker_task.cancel()
    try:
        await objective_worker_task
    except asyncio.CancelledError:
        pass
    task_worker_task.cancel()
    try:
        await task_worker_task
    except asyncio.CancelledError:
        pass
    heartbeat_task.cancel()
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        pass

app = FastAPI(title="Automaton Local API", version="0.7.0", lifespan=lifespan)
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

class TaskRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=12000)

class ObjectiveRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=4000)
    priority: int = Field(default=3, ge=1, le=5)
    due_at: str | None = Field(default=None, max_length=40)

class TeamRequest(BaseModel):
    task: str = Field(min_length=1, max_length=12000)

@app.get("/health")
def health():
    return {"status": "ok", "version": "0.6.0"}

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


@app.get("/tasks")
def task_list(limit: int = 50):
    return {"tasks": db.list_tasks(limit)}

@app.post("/tasks", status_code=202)
def task_create(req: TaskRequest):
    return db.create_task(req.prompt)

@app.get("/tasks/{task_id}")
def task_detail(task_id: int):
    task = db.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Tâche introuvable")
    return task

@app.delete("/tasks/{task_id}")
def task_cancel(task_id: int):
    if not db.cancel_task(task_id):
        task = db.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Tâche introuvable")
        raise HTTPException(status_code=409, detail="Seules les tâches en attente peuvent être annulées")
    return {"cancelled": True, "id": task_id}


@app.get("/objectives")
def objective_list(limit: int = 50):
    return {"objectives": db.list_objectives(limit)}

@app.post("/objectives", status_code=201)
async def objective_create(req: ObjectiveRequest):
    try:
        return await objectives.create_objective(req.title, req.description, req.priority, req.due_at)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc))

@app.get("/objectives/{objective_id}")
def objective_detail(objective_id: int):
    objective = db.get_objective(objective_id)
    if objective is None:
        raise HTTPException(status_code=404, detail="Objectif introuvable")
    return objective

@app.put("/objectives/{objective_id}/status")
def objective_status(objective_id: int, status: str):
    if status not in {"active", "paused", "cancelled"}:
        raise HTTPException(status_code=400, detail="Statut attendu : active, paused ou cancelled")
    if not db.set_objective_status(objective_id, status):
        if db.get_objective(objective_id) is None:
            raise HTTPException(status_code=404, detail="Objectif introuvable")
        raise HTTPException(status_code=409, detail="Transition de statut impossible")
    return db.get_objective(objective_id)

@app.post("/objectives/{objective_id}/steps/{step_id}/retry")
def objective_step_retry(objective_id: int, step_id: int):
    if not db.retry_objective_step(objective_id, step_id):
        objective = db.get_objective(objective_id)
        if objective is None:
            raise HTTPException(status_code=404, detail="Objectif introuvable")
        raise HTTPException(status_code=409, detail="Seule une étape en échec peut être relancée")
    return db.get_objective(objective_id)


@app.get("/objectives/{objective_id}/history")
def objective_history(objective_id: int):
    if db.get_objective(objective_id) is None:
        raise HTTPException(status_code=404, detail="Objectif introuvable")
    return db.objective_history(objective_id)

@app.post("/objectives/{objective_id}/supervise")
async def objective_supervise(objective_id: int):
    if db.get_objective(objective_id) is None:
        raise HTTPException(status_code=404, detail="Objectif introuvable")
    try:
        return await objectives.supervise_objective(objective_id)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc))

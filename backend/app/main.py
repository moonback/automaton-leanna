from fastapi import FastAPI,HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel,Field
from . import db,tools
from .agent import run_agent
app=FastAPI(title="Automaton Local API",version="0.1.0")
app.add_middleware(CORSMiddleware,allow_origins=["http://127.0.0.1:5173","file://"],allow_methods=["*"],allow_headers=["*"])
class RunRequest(BaseModel):prompt:str=Field(min_length=1,max_length=12000)
@app.on_event("startup")
def startup():db.init()
@app.get("/health")
def health():return {"status":"ok"}
@app.get("/workspace")
def workspace():return {"files":tools.list_files()}
@app.get("/history")
def history():return {"messages":db.history(100)}
@app.post("/agent/run")
async def agent_run(req:RunRequest):
 try:return await run_agent(req.prompt)
 except Exception as e:raise HTTPException(status_code=500,detail=str(e))

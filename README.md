# Automaton — Windows desktop agent

Electron + React + TypeScript desktop UI, FastAPI/Python backend, OpenRouter-compatible model API, SQLite persistence and a local workspace.

## Requirements
- Windows 10/11
- Node.js 20+
- Python 3.11+
- An OpenRouter API key (or another OpenAI-compatible provider key)

## Install
In PowerShell:
```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```
Set `OPENROUTER_API_KEY` in `backend/.env`, then start the API:
```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8765
```
In a second PowerShell at the repository root:
```powershell
npm install
npm run dev
```

## Autonomous capabilities
- **Heartbeat:** periodic background cycles. Disabled by default; configure with `PUT /heartbeat` (minimum interval 30 seconds). Status and run history: `GET /heartbeat`.
- **Persistent memory:** SQLite memories survive restarts. Use `POST /memory`, `GET /memory?q=...`, and `DELETE /memory/{id}`. The agent can also recall and store memories with tools.
- **Resource manager:** `GET /resources` reports workspace files, storage and runtime metadata. It does not terminate arbitrary processes or access files outside workspace.
- **Self-improvement:** `POST /improvements/apply` accepts a unified diff only for `backend/app/`. It requires a clean Git working tree and `AUTO_IMPROVE_ENABLED=true`; syntax compilation is run and failed patches are reverted. Successful patches remain uncommitted for human review. Keep this disabled unless you understand the risks and have a backup.
- **Multi-agent:** `POST /agents/run` runs planner, analyst and reviewer roles sequentially and returns each result. This is an initial orchestration layer, not parallel distributed execution.

## Provider
OpenRouter is the default: `AI_PROVIDER=openrouter`, `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`. Direct OpenAI is supported with `AI_PROVIDER=openai`, `OPENAI_API_KEY`, `OPENAI_BASE_URL` and `OPENAI_MODEL`. Credentials stay in the backend and are never sent to Electron's renderer.

## Safety
The agent's file tools are restricted to `backend/workspace/`; Python script execution has a 15-second timeout. The local API must remain bound to localhost and must not be exposed publicly. Never put secrets in the workspace or commit `.env`, virtual environments, SQLite databases or Python bytecode. If a real API key was ever committed, revoke it: deleting it in a later commit does not remove it from Git history.

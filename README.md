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

## Desktop modules
The Electron interface provides dedicated screens for Agent, Heartbeat, Memory, Resources, Multi-agents and Self-improvement. It polls the local API for connection status and displays module state.

## File de tâches persistantes\n- **Queue SQLite:** les tâches sont ajoutées avec `POST /tasks`, consultables avec `GET /tasks` et `GET /tasks/{id}`. Un worker local les exécute une par une ; `DELETE /tasks/{id}` annule uniquement une tâche encore en attente. Les tâches en cours sont remises en file au prochain démarrage du backend.\n\n## Autonomous capabilities
- **Heartbeat:** periodic background cycles. Disabled by default; configure interval and prompt in the desktop UI or use `PUT /heartbeat` (minimum interval 30 seconds). Status and run history: `GET /heartbeat`.
- **Persistent memory:** SQLite memories survive restarts. Add, search and delete them in the desktop UI or use `POST /memory`, `GET /memory?q=...`, and `DELETE /memory/{id}`. The agent can also recall and store memories with tools.
- **Resource manager:** the desktop UI and `GET /resources` report workspace files, storage and runtime metadata. It does not terminate arbitrary processes or access files outside workspace.
- **Self-improvement:** the desktop UI sends a unified diff to `POST /improvements/apply`. It is disabled unless `AUTO_IMPROVE_ENABLED=true`, requires a clean Git working tree and restricts patches to `backend/app/`. Python syntax compilation is run and failed patches are reverted. Successful patches remain uncommitted for human review. Keep this disabled unless you understand the risks and have a backup.
- **Multi-agent:** the desktop UI runs planner, analyst and reviewer roles sequentially. Each later role receives the earlier agents' output. This is an initial sequential orchestration layer, not parallel distributed execution.

## Provider
OpenRouter is the default: `AI_PROVIDER=openrouter`, `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`. Direct OpenAI is supported with `AI_PROVIDER=openai`, `OPENAI_API_KEY`, `OPENAI_BASE_URL` and `OPENAI_MODEL`. Credentials stay in the backend and are never sent to Electron's renderer.

## Safety
The agent's file tools are restricted to `backend/workspace/`; Python script execution has a 15-second timeout. The local API must remain bound to localhost and must not be exposed publicly. Never put secrets in the workspace or commit `.env`, virtual environments, SQLite databases or Python bytecode. If a real API key was ever committed, revoke it: deleting it in a later commit does not remove it from Git history.

# Automaton — Windows desktop starter

Electron + React + TypeScript desktop UI, FastAPI/Python agent backend, SQLite memory and a local workspace.

## Requirements
- Windows 10/11
- Node.js 20+
- Python 3.11+
- An OpenRouter API key (or another OpenAI-compatible provider key)

## Backend setup
In PowerShell:
```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` and set `OPENROUTER_API_KEY`. The default model is `openai/gpt-4o-mini`; choose any model available to your OpenRouter account and supporting tool/function calling.

Start the API:
```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8765
```

## Desktop UI
From the repository root in a second PowerShell:
```powershell
npm install
npm run dev
```

## Provider selection
OpenRouter is the default:
- `AI_PROVIDER=openrouter`
- `OPENROUTER_API_KEY`
- `OPENROUTER_MODEL`
- Optional `OPENROUTER_SITE_URL` and `OPENROUTER_APP_NAME` for OpenRouter attribution.

To use direct OpenAI, set `AI_PROVIDER=openai`, `OPENAI_API_KEY` and optionally `OPENAI_BASE_URL` / `OPENAI_MODEL`. The API key remains exclusively in the Python backend and is never sent to Electron's renderer.

## Agent permissions
The current agent is restricted to `backend/workspace/`. It can list, read and write files there and run existing Python scripts with a 15-second timeout. It has no arbitrary shell or administrator access. Do not expose the local API publicly or store secrets in the workspace.

## Repository hygiene
Never commit `.env`, virtual environments, SQLite runtime databases, Python bytecode or build output. If a real provider key was ever committed, revoke/rotate it in the provider dashboard; deleting the file in a later commit does not erase it from Git history.

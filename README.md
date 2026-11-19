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
The Electron interface provides dedicated screens for Agent, persistent Tasks, Objectives, Heartbeat, Memory, Resources, Multi-agents and Self-improvement. It polls the local API for connection status and displays module state.

## File de tâches persistantes et objectifs autonomes
- **Queue SQLite:** les tâches sont ajoutées avec `POST /tasks`, consultables avec `GET /tasks` et `GET /tasks/{id}`. Un worker local les exécute une par une ; `DELETE /tasks/{id}` annule uniquement une tâche encore en attente. Les tâches en cours sont remises en file au prochain démarrage du backend.

## Objectifs autonomes
- **Gestionnaire d'objectifs:** crée un objectif via `POST /objectives` avec un titre, une description et une priorité. Le planificateur IA génère 2 à 12 étapes persistées dans SQLite. `GET /objectives` et `GET /objectives/{id}` exposent la progression. Les étapes sont ajoutées séquentiellement à la file de tâches ; chaque étape attend la réussite de la précédente. Pause/reprise/annulation : `PUT /objectives/{id}/status?status=paused|active|cancelled`. Une étape en échec peut être relancée avec `POST /objectives/{id}/steps/{step_id}/retry`. Les étapes et objectifs sont conservés après redémarrage.
- Le planificateur ne garantit pas que le résultat final est correct : les critères de réussite doivent être vérifiés. L'exécution des étapes utilise les outils de l'agent et les mêmes limites du workspace.

### Supervision autonome des objectifs
- Un worker local examine les objectifs actifs toutes les 60 secondes lorsqu'aucune étape n'est en cours. La supervision peut être déclenchée manuellement avec `POST /objectives/{id}/supervise`.
- L'évaluateur examine les résultats et erreurs d'étapes, puis choisit de continuer, de clôturer après validation, de proposer un plan correctif ou de signaler un blocage.
- Les adaptations ajoutent des étapes au plan sans écraser les anciennes versions. Les étapes en échec conservées dans l'historique sont marquées comme ignorées uniquement lorsqu'un plan correctif est accepté.
- `GET /objectives/{id}/history` expose les événements et révisions du plan. Le bouton Historique de l'interface affiche les événements.
- Une erreur fournisseur est journalisée et retentée après le délai de supervision. Un objectif bloqué nécessite une action explicite : examen humain, relance d'étape ou reprise.
- Limite : l'évaluation repose sur le modèle configuré et les preuves présentes dans les résultats. Elle ne constitue pas une preuve formelle de réussite. Le superviseur ne modifie pas le code de lui-même.

## Autonomous capabilities
- **Heartbeat:** periodic background cycles. Disabled by default; configure interval and prompt in the desktop UI or use `PUT /heartbeat` (minimum interval 30 seconds). Status and run history: `GET /heartbeat`.
- **Persistent memory:** SQLite memories survive restarts. Add, search and delete them in the desktop UI or use `POST /memory`, `GET /memory?q=...`, and `DELETE /memory/{id}`. The agent can also recall and store memories with tools.
- **Resource manager:** the desktop UI and `GET /resources` report workspace files, storage and runtime metadata. It does not terminate arbitrary processes or access files outside workspace.
- **Self-improvement:** the desktop UI sends a unified diff to `POST /improvements/apply`. It is disabled unless `AUTO_IMPROVE_ENABLED=true`, requires a clean Git working tree and restricts patches to `backend/app/`. Python syntax compilation is run and failed patches are reverted. Successful patches remain uncommitted for human review. Keep this disabled unless you understand the risks and have a backup.
- **Multi-agent:** the desktop UI runs planner, analyst and reviewer roles sequentially. Each later role receives the earlier agents' output. This is an initial sequential orchestration layer, not parallel distributed execution.

## Provider
OpenRouter is the default: `AI_PROVIDER=openrouter`, `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`. Direct OpenAI is supported with `AI_PROVIDER=openai`, `OPENAI_API_KEY`, `OPENAI_BASE_URL` and `OPENAI_MODEL`. Credentials stay in the backend and are never sent to Electron's renderer.

## Safety
The agent's file tools are restricted to `backend/workspace/`; Python script execution has a 15-second timeout. The local API must remain bound to localhost and must not be exposed publicly. Never put secrets in the workspace or commit `.env`, virtual environments, SQLite databases or Python bytecode. If a real API key was ever committed, revoke it: deleting it in a later commit does not remove it from Git history.


## Vérification indépendante des résultats (0.8.0)
- `POST /verification/workspace` accepte de 1 à 50 contrôles explicites, exécutés en lecture seule dans le workspace.
- Contrôles disponibles : `exists` (présence), `contains` (texte attendu), `sha256` (empreinte exacte), `changed_since` (comparaison avec une empreinte de référence) et `python_syntax` (compilation syntaxique sans exécuter le script).
- Exemple : `{"checks":[{"kind":"exists","path":"rapport.md"},{"kind":"contains","path":"rapport.md","text":"Conclusion"},{"kind":"python_syntax","path":"script.py"}]}`. La réponse donne le nombre de contrôles réussis/échoués, un résultat par contrôle et l'empreinte SHA-256 observée.
- Les chemins absolus, traversées hors workspace, contrôles inconnus et fichiers de plus de 2 Mo sont refusés. Aucun code arbitraire n'est exécuté.
- Tests unitaires standard-library : `cd backend && python -m unittest discover -s tests -v`.
- GitHub Actions exécute les tests backend sur Ubuntu et Windows, puis construit l'interface avec `npm ci && npm run build`.
- Limite importante : cette première version fournit des contrôles déterministes sur les artefacts du workspace. Elle ne certifie pas encore automatiquement les effets externes (réseau, processus, services) et ne remplace pas les critères d'acceptation propres à chaque objectif.

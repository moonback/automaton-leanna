# Automaton — Windows starter

## Prérequis
Windows 10/11, Node.js 20+, Python 3.11+ et une clé API compatible OpenAI Chat Completions.

## Installation du backend
Dans PowerShell :
```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```
Renseigne `OPENAI_API_KEY`, `OPENAI_BASE_URL` et `OPENAI_MODEL` dans `backend/.env`, puis lance :
```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8765
```

## Installation de l'interface
Dans un second PowerShell, à la racine :
```powershell
npm install
npm run dev
```

## Sécurité
L'agent est limité à `backend/workspace/`. Il peut lister, lire et écrire des fichiers et exécuter des scripts Python existants de cet espace (15 secondes maximum), sans shell arbitraire ni privilèges administrateur. Ne publie pas le backend sur Internet et ne place aucun secret dans le workspace.

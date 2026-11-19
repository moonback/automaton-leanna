@echo off
title Automaton Launcher

echo ============================================
echo   Automaton - demarrage backend + frontend
echo ============================================
echo.

echo [1/2] Demarrage du backend (uvicorn, port 8765)...
rem --reload-dir app : sinon uvicorn redemarre quand l'agent ecrit un .py dans workspace\
start "Automaton Backend" cmd /k "cd /d "%~dp0backend" && uvicorn app.main:app --reload --reload-dir app --host 127.0.0.1 --port 8765"

echo [2/2] Demarrage du frontend (vite + electron)...
start "Automaton Frontend" cmd /k "cd /d "%~dp0" && npm run dev"

echo.
echo Les deux fenetres sont lancees :
echo  - Backend  : http://127.0.0.1:8765
echo  - Frontend : http://127.0.0.1:5173 (+ fenetre Electron)
echo.
echo Fermez les deux fenetres "Automaton Backend" / "Automaton Frontend" pour tout arreter.
timeout /t 5 >nul

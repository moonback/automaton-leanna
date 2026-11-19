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
- Limite importante : les contrôles externes de la version 1.0.0 vérifient uniquement les services HTTP et ports TCP locaux en loopback. Ils ne prouvent pas l'identité du processus, sa stabilité dans le temps ni les effets sur un service distant.


## Vérification des étapes d'objectifs (0.9.0)
- Chaque nouvelle étape doit inclure au moins un critère d'acceptation déterministe (exists, contains ou python_syntax) sur un fichier du workspace.
- Les critères sont validés avant l'enregistrement du plan et conservés en SQLite. Les plans correctifs doivent fournir les mêmes critères.
- Une étape d'objectif ne passe à succeeded que si l'agent a réellement exécuté un outil de production (write_file ou run_python) et si tous les contrôles du workspace passent ensuite.
- La trace des appels d'outils, la réponse de l'agent et les résultats des contrôles sont archivés dans les événements de l'objectif. Une étape sans critères ou sans action confirmée échoue par défaut.
- Les tâches génériques hors objectifs conservent leur comportement précédent. Les objectifs déjà présents avant cette version n'ont pas de critères migrés automatiquement : leurs prochaines étapes échoueront en validation tant qu'elles ne sont pas replanifiées avec des critères.
- Cette validation porte sur les artefacts du workspace ; elle ne certifie pas les effets externes (services, réseau, processus distants).


## Vérification des effets externes locaux (1.0.0)
Les étapes d'objectif peuvent désormais vérifier des services locaux après une action :
- `http_status` : effectue un GET HTTP sans suivre les redirections et compare le code observé au code attendu. `must_transition: true` exige que le service ne soit pas déjà conforme avant l'action.
- `tcp_port_open` : vérifie qu'un port TCP local accepte une connexion. `must_transition: true` exige que le port soit fermé avant l'action puis ouvert après.
- Les sondes sont strictement limitées à `localhost`, `127.0.0.1` et `::1`. Aucun hôte du réseau local ou d'Internet n'est accepté, afin de limiter les risques SSRF.
- Les requêtes HTTP utilisent un délai court, désactivent les proxys d'environnement et n'envoient aucune donnée d'authentification.
- Les preuves externes sont regroupées avec les contrôles workspace dans l'événement de vérification de l'étape.
- API manuelle : `POST /verification/external` avec `{"checks":[{"kind":"http_status","url":"http://127.0.0.1:8000/health","expected_status":200}]}`. Les exécutions sont conservées dans `GET /verification/history`.
- Tests dédiés : `python -m unittest discover -s tests -v`.

Limites : ces sondes prouvent uniquement qu'un service local répond ou qu'un port accepte une connexion au moment du contrôle. Elles ne prouvent ni l'identité du processus, ni sa stabilité dans le temps, ni la disponibilité depuis un autre appareil. Les effets distants et les actions réseau avec mutation restent désactivés.


## Exécution contrainte et gestion des processus (1.1.0)

### Exécution Python
- `run_python` passe par `backend/app/sandbox.py` : interpréteur isolé (`-I`), environnement réduit, exécution sans shell, délai maximal de 30 secondes, sortie capturée limitée et arrêt du groupe de processus au timeout.
- Sur les systèmes POSIX, limites de ressources : mémoire virtuelle 512 Mo, temps CPU 30 secondes, fichiers écrits par processus 10 Mo et 64 descripteurs.
- Les processus gérés peuvent vivre plus longtemps : limite CPU POSIX d'une heure, mémoire 512 Mo, fichiers écrits 10 Mo et sortie journal plafonnée à 2 Mo.
- **Limite de sécurité** : ce profil est un sous-processus contraint, pas un sandbox OS. Le code Python conserve les droits du compte Windows/utilisateur qui exécute Automaton et peut accéder aux fichiers et au réseau auxquels ce compte a accès. Les limites POSIX ne sont pas équivalentes sur Windows. Ne pas exécuter de code non fiable ou hostile.

### Gestionnaire de processus
- Outils agent : `start_process`, `list_processes`, `stop_process`.
- API : `POST /processes` avec `{"path":"worker.py"}`, `GET /processes`, `GET /processes/{id}`, `GET /processes/{id}/logs`, `DELETE /processes/{id}`.
- Seuls les scripts Python existants du workspace peuvent être démarrés. Aucun shell ou argument de commande arbitraire n'est accepté.
- PID, script, état, code de sortie et chemin du journal sont persistés dans SQLite. Les journaux sont limités à 2 Mo par processus.
- Arrêt limité aux processus dont le handle appartient à la session backend courante. Après redémarrage, les anciens processus sont marqués `orphaned` et ne sont pas tués automatiquement, afin d'éviter de signaler un PID réutilisé. Leur arrêt nécessite une intervention manuelle.
- Sur Windows, l'arrêt utilise `taskkill /T /F` pour viser l'arbre du processus géré.

### Tests
`python -m unittest discover -s tests -v` couvre les contrôles de chemin, le délai d'exécution, le cycle démarrage/arrêt et la sécurité des processus orphelins.

## Containment Windows et tableau de bord des processus (1.2.0)

### Job Objects natifs
Sous Windows 10/11, Automaton crée chaque processus Python en état suspendu, l'assigne à un Windows Job Object, puis le reprend. Cela évite que le script commence avant l'application des limites. Le Job Object applique :
- mémoire maximale par processus et pour le groupe : 512 Mo ;
- temps CPU utilisateur maximal par processus : 30 secondes pour une exécution ponctuelle, 1 heure pour un processus géré ;
- maximum de 16 processus enfants pour une exécution ponctuelle et 32 pour un processus géré ;
- terminaison de l'arbre de processus lorsque le handle du Job Object est fermé.

L'assignation au Job Object échoue de manière fermée : le processus suspendu est terminé si les limites ne peuvent pas être installées. Les processus gérés sont arrêtés automatiquement à la fermeture du backend par la règle `KILL_ON_JOB_CLOSE`. Leur historique est alors marqué `interrupted` au prochain démarrage.

### Interface de supervision
Un nouvel écran **Processus** permet de :
- démarrer un script Python existant du workspace ;
- suivre PID, état, date de démarrage et profil de confinement ;
- consulter les dernières lignes du journal ;
- arrêter un processus et son arbre de descendants.

L'interface actualise la liste automatiquement. Les journaux sont plafonnés à 2 Mo par processus.

### Limites de sécurité
Les Windows Job Objects sont un mécanisme de gestion et de confinement des ressources, **pas une frontière de sécurité**. Ils ne restreignent pas les accès aux fichiers, au registre, aux identifiants de l'utilisateur ni au réseau. Le code exécuté conserve les permissions du compte Windows d'Automaton. Il ne faut pas exécuter de code hostile ou non fiable.

Une isolation de sécurité plus forte nécessitera une étape distincte : AppContainer avec jeton restreint et capacités minimales, ou exécution dans Windows Sandbox / une VM. La version 1.2.0 ne prétend pas fournir cette isolation.

Tests ajoutés : `backend/tests/test_windows_job.py` vérifie l'assignation et l'arrêt d'un processus suspendu sur Windows ; le test est ignoré sur les autres systèmes.

## Isolation Windows renforcée avec Windows Sandbox (1.3.0)

Le gestionnaire de processus propose deux profils sur Windows :

- `job_object` : profil léger de la version 1.2.0. Il limite les ressources et contrôle l'arbre de processus, mais ne réduit pas les permissions du compte.
- `windows_sandbox` : lance le script dans une machine virtuelle Windows Sandbox dédiée. Ce profil est sélectionnable dans l'écran **Processus** ou via `POST /processes` avec `{"path":"worker.py","isolation":"windows_sandbox"}`.

### Configuration du guest
- Réseau désactivé (`Networking=Disable`).
- Presse-papiers désactivé.
- vGPU désactivé.
- Mode Protected Client activé.
- Mémoire guest fixée à 2 Go.
- Seul le dossier parent du script est monté en lecture seule.
- Le runtime Python de base est monté en lecture seule ; si le backend utilise un virtualenv, son dossier `site-packages` est également monté en lecture seule.
- Un répertoire unique par session est monté en écriture pour le lanceur et les journaux. Il ne contient pas les autres fichiers du workspace.

Le lancement échoue explicitement si Windows Sandbox n'est pas installé/activé ou si le runtime Python n'a pas une structure compatible. Une seule session Windows Sandbox est autorisée simultanément. L'API suit le PID hôte de `WindowsSandbox.exe`, et non le PID Python dans le guest.

### Prérequis et limites
- Windows 10/11 Pro, Entreprise ou Éducation avec la fonctionnalité **Windows Sandbox** activée.
- Redémarrer Windows après activation de la fonctionnalité.
- Le script peut lire les fichiers présents dans son dossier parent et le runtime Python monté. Ne stockez pas de secrets dans ces emplacements.
- Le dossier de sortie mappé est accessible en écriture depuis le guest ; le répertoire de travail du script pointe vers ce dossier, et ses journaux/sorties doivent être considérés comme non fiables. La sortie console est plafonnée à 2 Mo.
- Une fermeture normale du backend demande l'arrêt des sessions qu'il possède. Après un crash brutal du backend, une session Sandbox peut rester ouverte : fermez-la manuellement depuis Windows Sandbox. Les anciens PID ne sont jamais tués automatiquement après redémarrage.
- Le profil Sandbox ne garantit pas un plafond CPU strict. La mémoire du guest est limitée à 2 Go ; les limites CPU/processus détaillées restent celles du profil Job Object, pas du guest Sandbox.
- Les tests automatisés valident la génération de configuration et les garde-fous ; ils ne remplacent pas un test réel sur une édition Windows compatible.

Cette voie utilise Windows Sandbox plutôt qu'un AppContainer créé directement par Win32 : elle fournit une frontière VM prise en charge par Windows et permet de désactiver le réseau sans ajouter de dépendances natives tierces.


## Gestionnaire de permissions, approbations et audit (1.4.0)

Automaton applique désormais un contrôle de capacités avant l'exécution des outils de l'agent.

### Profils de confiance
- `observe_only` : lecture du workspace, consultation des processus et recherche mémoire.
- `workspace_write` : ajoute l'écriture dans le workspace et la création de souvenirs.
- `sandbox_execution` : ajoute le démarrage et l'arrêt de processus gérés, soumis à approbation ; les démarrages utilisent Windows Sandbox. Requiert une édition Windows compatible.
- `admin` : toutes les capacités actuellement exposées, mais les actions sensibles restent soumises à approbation.

Le profil initial est `observe_only`. Le changement de profil est explicite depuis l'interface **Permissions** ou `PUT /permissions/profile`. Le refus est appliqué si l'outil n'est pas autorisé par le profil.

### Approbation humaine
Les appels `start_process`, `stop_process` et `run_python` ne sont jamais exécutés directement par l'agent : une demande est créée, valable dix minutes. L'utilisateur peut l'approuver ou la refuser depuis la file d'approbation. L'exécution est à usage unique et le profil actif est revérifié au moment de l'exécution. `run_python` reste réservé au profil `admin` et demeure un sous-processus contraint, pas une frontière de sécurité OS.

API : `GET /permissions`, `PUT /permissions/profile`, `GET /permissions/requests`, `POST /permissions/requests/{id}/decision`, `GET /permissions/audit`.

### Journal d'audit et limites
- Les décisions, changements de profil, demandes et résultats sont ajoutés à une table SQLite avec déclencheurs empêchant les modifications/suppressions via SQL ordinaire.
- Les arguments sont résumés et les champs de type secret/token/mot de passe sont masqués ; le contenu de fichiers/patchs est remplacé par longueur et empreinte SHA-256 dans l'audit.
- Les demandes d'approbation conservent les arguments nécessaires à leur exécution dans la base locale ; protégez donc le fichier SQLite et le répertoire de données.
- Le backend local n'authentifie pas les clients locaux. Ce gestionnaire protège les appels d'outils de l'agent et ne constitue pas une frontière contre un autre processus malveillant exécuté sous le même compte Windows.
- Les permissions et Windows Sandbox sont deux couches distinctes : les premières autorisent les capacités, la seconde isole certains processus.

Tests ajoutés : `backend/tests/test_permissions.py` couvre le refus par défaut, les profils, l'approbation à usage unique, le refus humain et l'append-only du journal.

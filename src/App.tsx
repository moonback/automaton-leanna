import { useEffect, useState } from 'react';
import {
  Activity, Bot, Brain, Cpu, Folder, Gauge, GitBranch, ListTodo, Play, RefreshCw, Target,
  Send, Settings, ShieldCheck, Trash2, Users, Zap, CircleCheck, Clock3, HardDrive, MemoryStick, ArrowUpRight
} from 'lucide-react';

const API = 'http://127.0.0.1:8765';
type Message = { role: 'user' | 'assistant'; content: string };
type Page = 'overview' | 'agent' | 'tasks' | 'objectives' | 'heartbeat' | 'memory' | 'resources' | 'agents' | 'improvements';
type Memory = { id: number; content: string; tags: string; importance: number; created_at: string };
type HeartbeatRun = { id: number; status: string; summary: string; error: string; started_at: string };
type HeartbeatConfig = { enabled: number; interval_seconds: number; prompt: string };
type ResourceSnapshot = {
  platform: string; python: string; pid: number;
  workspace: { file_count: number; total_bytes: number; files: { path: string; size: number }[] };
  storage: { total_bytes: number; free_bytes: number };
  system: { cpu_percent: number; memory_percent: number; memory_used_bytes: number; memory_total_bytes: number; disk_percent: number; network_sent_bytes: number; network_received_bytes: number; gpu_available: boolean };
};
type AgentResult = { mode: string; agents: Record<string, string> };
type Objective = { id:number; title:string; description:string; status:string; priority:number; total_steps:number; completed_steps:number; supervisor_state?:string; supervisor_note?:string; supervised_at?:string; steps?: {id:number;position:number;title:string;description:string;status:string;result:string;error:string}[] };
type Task = { id: number; prompt: string; status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'; result: string; error: string; created_at: string; updated_at: string };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...init, headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) }
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || `Erreur HTTP ${response.status}`);
  return data as T;
}
function formatBytes(value: number) {
  if (value < 1024) return `${value} o`;
  const units = ['Ko', 'Mo', 'Go', 'To'];
  let size = value / 1024, unit = 0;
  while (size >= 1024 && unit < units.length - 1) { size /= 1024; unit++; }
  return `${size.toFixed(1)} ${units[unit]}`;
}

export default function App() {
  const [page, setPage] = useState<Page>('overview');
  const [messages, setMessages] = useState<Message[]>([{ role: 'assistant', content: 'Automaton est prêt. Décris une tâche à accomplir dans son espace de travail.' }]);
  const [prompt, setPrompt] = useState('');
  const [taskPrompt, setTaskPrompt] = useState('');
  const [tasks, setTasks] = useState<Task[]>([]);
  const [objectives, setObjectives] = useState<Objective[]>([]);
  const [objectiveEvents, setObjectiveEvents] = useState<Record<number, {id:number;event_type:string;message:string;details?:string;created_at:string}[]>>({});
  const [objectiveRevisions, setObjectiveRevisions] = useState<Record<number, {id:number;revision:number;reason:string;plan_json:string;created_at:string}[]>>({});
  const [goalTitle, setGoalTitle] = useState('');
  const [goalDescription, setGoalDescription] = useState('');
  const [goalPriority, setGoalPriority] = useState(3);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('Connexion…');
  const [workspace, setWorkspace] = useState<string[]>([]);
  const [provider, setProvider] = useState('openrouter');
  const [model, setModel] = useState('chargement…');
  const [memories, setMemories] = useState<Memory[]>([]);
  const [memoryText, setMemoryText] = useState('');
  const [memoryTags, setMemoryTags] = useState('');
  const [importance, setImportance] = useState(3);
  const [heartbeat, setHeartbeat] = useState<HeartbeatConfig | null>(null);
  const [heartbeatRuns, setHeartbeatRuns] = useState<HeartbeatRun[]>([]);
  const [resources, setResources] = useState<ResourceSnapshot | null>(null);
  const [teamTask, setTeamTask] = useState('');
  const [teamResult, setTeamResult] = useState<AgentResult | null>(null);
  const [patch, setPatch] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');

  async function refreshBase() {
    try {
      const [health, files, config] = await Promise.all([
        request<{ status: string; version: string }>('/health'),
        request<{ files: string[] }>('/workspace'),
        request<{ provider: string; model: string }>('/config')
      ]);
      setStatus(`Connecté · API ${health.version}`);
      setWorkspace(files.files || []);
      setProvider(config.provider);
      setModel(config.model);
    } catch { setStatus('Backend indisponible'); }
  }
  async function refreshHeartbeat() {
    const data = await request<{ config: HeartbeatConfig; runs: HeartbeatRun[] }>('/heartbeat');
    setHeartbeat(data.config); setHeartbeatRuns(data.runs);
  }
  async function refreshMemories() {
    const data = await request<{ memories: Memory[] }>('/memory');
    setMemories(data.memories);
  }
  async function refreshResources() { setResources(await request<ResourceSnapshot>('/resources')); }
  async function refreshTasks() { const data = await request<{ tasks: Task[] }>('/tasks'); setTasks(data.tasks); }
  async function refreshObjectives() { const data = await request<{ objectives: Objective[] }>('/objectives'); const details = await Promise.all(data.objectives.map(item => request<Objective>(`/objectives/${item.id}`))); setObjectives(details); }
  async function refreshAll() {
    setError('');
    await refreshBase();
    try { await Promise.all([refreshHeartbeat(), refreshMemories(), refreshResources(), refreshTasks(), refreshObjectives()]); }
    catch (e) { setError(e instanceof Error ? e.message : 'Erreur de chargement'); }
  }
  useEffect(() => {
    void refreshAll();
    const id = window.setInterval(() => { void refreshBase(); void refreshTasks().catch(() => {}); void refreshObjectives().catch(() => {}); }, 3000);
    return () => window.clearInterval(id);
  }, []);

  async function send() {
    const value = prompt.trim();
    if (!value || busy) return;
    setMessages(current => [...current, { role: 'user', content: value }]);
    setPrompt(''); setBusy(true); setError('');
    try {
      const data = await request<{ answer: string }>('/agent/run', { method: 'POST', body: JSON.stringify({ prompt: value }) });
      setMessages(current => [...current, { role: 'assistant', content: data.answer || 'Tâche terminée.' }]);
      void refreshBase();
    } catch (e) {
      setMessages(current => [...current, { role: 'assistant', content: `Erreur : ${e instanceof Error ? e.message : 'Erreur inconnue'}` }]);
    } finally { setBusy(false); }
  }
  async function enqueueTask() {
    const value = taskPrompt.trim();
    if (!value) return;
    setError(''); setNotice('');
    try {
      await request('/tasks', { method: 'POST', body: JSON.stringify({ prompt: value }) });
      setTaskPrompt(''); await refreshTasks(); setNotice('Tâche ajoutée à la file.');
    } catch (e) { setError(e instanceof Error ? e.message : 'Ajout impossible'); }
  }
  async function createObjective() {
    if (!goalTitle.trim() || !goalDescription.trim()) return;
    setBusy(true); setError(''); setNotice('');
    try {
      await request('/objectives', { method:'POST', body:JSON.stringify({title:goalTitle,description:goalDescription,priority:goalPriority}) });
      setGoalTitle(''); setGoalDescription(''); await refreshObjectives(); setNotice('Objectif planifié et enregistré.');
    } catch (e) { setError(e instanceof Error ? e.message : 'Planification impossible'); }
    finally { setBusy(false); }
  }
  async function changeObjectiveStatus(id:number,status:'active'|'paused'|'cancelled') {
    try { await request(`/objectives/${id}/status?status=${status}`,{method:'PUT'}); await refreshObjectives(); }
    catch(e) { setError(e instanceof Error ? e.message : 'Modification impossible'); }
  }
  async function superviseObjective(id:number) {
    try { await request(`/objectives/${id}/supervise`,{method:'POST'}); await refreshObjectives(); }
    catch(e) { setError(e instanceof Error ? e.message : 'Supervision impossible'); }
  }
  async function loadObjectiveHistory(id:number) {
    try { const data=await request<{events:{id:number;event_type:string;message:string;details?:string;created_at:string}[];revisions:{id:number;revision:number;reason:string;plan_json:string;created_at:string}[]}>(`/objectives/${id}/history`); setObjectiveEvents(current=>({...current,[id]:data.events})); setObjectiveRevisions(current=>({...current,[id]:data.revisions})); }
    catch(e) { setError(e instanceof Error ? e.message : 'Historique indisponible'); }
  }
  async function retryObjectiveStep(objectiveId:number,stepId:number) {
    try { await request(`/objectives/${objectiveId}/steps/${stepId}/retry`,{method:'POST'}); await refreshObjectives(); }
    catch(e) { setError(e instanceof Error ? e.message : 'Relance impossible'); }
  }
  async function cancelTask(id: number) {
    try { await request(`/tasks/${id}`, { method: 'DELETE' }); await refreshTasks(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Annulation impossible'); }
  }
  async function saveMemory() {
    if (!memoryText.trim()) return;
    setError(''); setNotice('');
    try {
      await request('/memory', { method: 'POST', body: JSON.stringify({ content: memoryText, tags: memoryTags, importance }) });
      setMemoryText(''); setMemoryTags(''); await refreshMemories(); setNotice('Souvenir enregistré.');
    } catch (e) { setError(e instanceof Error ? e.message : 'Enregistrement impossible'); }
  }
  async function deleteMemory(id: number) {
    try { await request(`/memory/${id}`, { method: 'DELETE' }); await refreshMemories(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Suppression impossible'); }
  }
  async function saveHeartbeat() {
    if (!heartbeat) return;
    try {
      const data = await request<{ config: HeartbeatConfig }>('/heartbeat', {
        method: 'PUT', body: JSON.stringify(heartbeat)
      });
      setHeartbeat(data.config); await refreshHeartbeat(); setNotice('Configuration du heartbeat enregistrée.');
    } catch (e) { setError(e instanceof Error ? e.message : 'Configuration impossible'); }
  }
  async function runTeam() {
    if (!teamTask.trim() || busy) return;
    setBusy(true); setError(''); setTeamResult(null);
    try {
      setTeamResult(await request<AgentResult>('/agents/run', {
        method: 'POST', body: JSON.stringify({ task: teamTask })
      }));
    } catch (e) { setError(e instanceof Error ? e.message : 'Échec des agents'); }
    finally { setBusy(false); }
  }
  async function applyPatch() {
    if (!patch.trim() || busy) return;
    if (!window.confirm('Appliquer ce patch au code local ? Vérifie que le dépôt est sauvegardé et propre.')) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await request<{ applied: boolean; validation: string; diff: string; note: string }>('/improvements/apply', {
        method: 'POST', body: JSON.stringify({ patch })
      });
      setNotice(`Patch appliqué · ${result.validation}. ${result.note}`);
    } catch (e) { setError(e instanceof Error ? e.message : 'Patch refusé'); }
    finally { setBusy(false); }
  }

  const nav: { id: Page; label: string; icon: typeof Bot }[] = [
    { id: 'overview', label: 'Vue d’ensemble', icon: Gauge },
    { id: 'agent', label: 'Agent', icon: Bot },
    { id: 'tasks', label: 'File de tâches', icon: ListTodo },
    { id: 'objectives', label: 'Objectifs', icon: Target },
    { id: 'heartbeat', label: 'Heartbeat', icon: Activity },
    { id: 'memory', label: 'Mémoire', icon: Brain },
    { id: 'resources', label: 'Ressources', icon: Gauge },
    { id: 'agents', label: 'Multi-agents', icon: Users },
    { id: 'improvements', label: 'Auto-amélioration', icon: GitBranch }
  ];
  const titles: Record<Page, string> = {
    overview: 'Centre de contrôle', agent: 'Agent', tasks: 'File de tâches persistantes', objectives: 'Objectifs autonomes', heartbeat: 'Heartbeat', memory: 'Mémoire persistante',
    resources: 'Gestionnaire de ressources', agents: 'Équipe multi-agents',
    improvements: 'Auto-amélioration'
  };

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand"><div className="logo"><Bot /></div><div><b>Automaton</b><small>LOCAL AGENT · 1.1.0</small></div></div>
        <div className="navgroup">{nav.map(item => {
          const Icon = item.icon;
          return <button key={item.id} className={`nav ${page === item.id ? 'active' : ''}`} onClick={() => { setPage(item.id); setError(''); setNotice(''); }}>
            <Icon size={17} />{item.label}
          </button>;
        })}</div>
        <div className="sidebottom"><span className={`dot ${status.startsWith('Connecté') ? 'ok' : ''}`} />{status}</div>
      </aside>
      <main>
        <header><div><h1>{titles[page]}</h1><p>Automatisation locale · {provider} / {model}</p></div><button className="iconbtn" onClick={() => void refreshAll()} title="Actualiser"><RefreshCw size={17} /></button></header>
        {error && <div className="alert error">{error}</div>}
        {notice && <div className="alert success">{notice}</div>}


        {page === 'overview' && <>
          <section className="overview-status">
            <div className="status-orb"><CircleCheck size={27}/></div>
            <div className="overview-status-copy"><span className="eyebrow">ÉTAT DU SYSTÈME</span><h2>{status.startsWith('Connecté') ? 'Automaton opérationnel' : 'Backend indisponible'}</h2><p>{status} · {provider} / {model}</p></div>
            <div className="supervision-state"><span className={heartbeat?.enabled ? 'live-dot' : 'idle-dot'} />Supervision {heartbeat?.enabled ? 'active' : 'en pause'}</div>
          </section>
          <section className="overview-metrics">
            <article className="overview-metric"><div className="metric-icon cyan"><Cpu/></div><div><small>CPU</small><strong>{resources ? \`\${resources.system.cpu_percent.toFixed(0)}%\` : '—'}</strong><span>Utilisation actuelle</span></div><div className="meter"><i style={{width:\`\${resources?.system.cpu_percent || 0}%\`}}/></div></article>
            <article className="overview-metric"><div className="metric-icon violet"><MemoryStick/></div><div><small>RAM</small><strong>{resources ? \`\${resources.system.memory_percent.toFixed(0)}%\` : '—'}</strong><span>{resources ? \`\${formatBytes(resources.system.memory_used_bytes)} / \${formatBytes(resources.system.memory_total_bytes)}\` : 'Chargement…'}</span></div><div className="meter"><i style={{width:\`\${resources?.system.memory_percent || 0}%\`}}/></div></article>
            <article className="overview-metric"><div className="metric-icon blue"><HardDrive/></div><div><small>STOCKAGE LIBRE</small><strong>{resources ? formatBytes(resources.storage.free_bytes) : '—'}</strong><span>Sur {resources ? formatBytes(resources.storage.total_bytes) : '—'}</span></div><div className="meter"><i style={{width:\`\${resources?.system.disk_percent || 0}%\`}}/></div></article>
            <article className="overview-metric"><div className="metric-icon green"><Bot/></div><div><small>ÉQUIPE MULTI-AGENTS</small><strong>3 rôles</strong><span>Exécution séquentielle</span></div><div className="metric-foot">Planifier · Analyser · Réviser</div></article>
          </section>
          <section className="overview-grid">
            <article className="dash-card health-card"><div className="dash-heading"><h3><Activity/> Supervision autonome</h3><span className={heartbeat?.enabled ? 'tag-success' : 'tag-muted'}>{heartbeat?.enabled ? 'ACTIVE' : 'INACTIVE'}</span></div>
              <div className="health-main"><div className="health-ring"><ShieldCheck size={35}/></div><div><strong>{heartbeat?.enabled ? 'Cycle activé' : 'En attente'}</strong><p>{heartbeat ? \`Vérification toutes les \${heartbeat.interval_seconds}s\` : 'Configuration non chargée'}</p></div></div>
              <div className="health-detail"><span>Dernier cycle</span><b>{heartbeatRuns[0]?.started_at || 'Aucun cycle enregistré'}</b></div>
              <div className="health-detail"><span>Résultat</span><b>{heartbeatRuns[0]?.summary || heartbeatRuns[0]?.error || 'En attente de données'}</b></div>
              <button className="dash-link" onClick={()=>setPage('heartbeat')}>Configurer le heartbeat <ArrowUpRight size={14}/></button>
            </article>
            <article className="dash-card"><div className="dash-heading"><h3><Target/> Objectifs en cours</h3><button className="dash-link" onClick={()=>setPage('objectives')}>Tout voir <ArrowUpRight size={14}/></button></div>
              {objectives.filter(x=>x.status==='active'||x.status==='paused').slice(0,4).map(goal=><div className="goal-mini" key={goal.id}><div><b>{goal.title}</b><span>{goal.completed_steps || 0}/{goal.total_steps || 0} étapes · {goal.status}</span></div><strong>{goal.total_steps ? Math.round(goal.completed_steps/goal.total_steps*100) : 0}%</strong><div className="progress"><div style={{width:\`\${goal.total_steps ? goal.completed_steps/goal.total_steps*100 : 0}%\`}}/></div></div>)}
              {!objectives.some(x=>x.status==='active'||x.status==='paused') && <p className="dash-empty">Aucun objectif actif. Crée un objectif pour démarrer une mission longue durée.</p>}
            </article>
            <article className="dash-card"><div className="dash-heading"><h3><ListTodo/> File des missions</h3><button className="dash-link" onClick={()=>setPage('tasks')}>Voir la file <ArrowUpRight size={14}/></button></div>
              <div className="task-counts"><div><strong>{tasks.filter(t=>t.status==='running').length}</strong><span>En cours</span></div><div><strong>{tasks.filter(t=>t.status==='queued').length}</strong><span>En attente</span></div><div><strong>{tasks.filter(t=>t.status==='succeeded').length}</strong><span>Terminées</span></div></div>
              {tasks.slice(0,4).map(task=><div className="activity-line" key={task.id}><span className={task.status==='failed'?'activity-dot warn':'activity-dot'}></span><div><b>{task.prompt}</b><small>{task.status} · {task.updated_at}</small></div></div>)}
              {!tasks.length && <p className="dash-empty">Aucune tâche enregistrée.</p>}
            </article>
            <article className="dash-card resource-summary"><div className="dash-heading"><h3><Gauge/> Ressources système</h3><button className="dash-link" onClick={()=>setPage('resources')}>Détails <ArrowUpRight size={14}/></button></div>
              {resources ? <><div className="resource-line"><span>CPU</span><b>{resources.system.cpu_percent.toFixed(1)}%</b></div><div className="mini-meter"><i style={{width:\`\${resources.system.cpu_percent}%\`}}/></div><div className="resource-line"><span>Mémoire vive</span><b>{resources.system.memory_percent.toFixed(1)}%</b></div><div className="mini-meter"><i style={{width:\`\${resources.system.memory_percent}%\`}}/></div><div className="resource-line"><span>Disque utilisé</span><b>{resources.system.disk_percent.toFixed(1)}%</b></div><div className="mini-meter"><i style={{width:\`\${resources.system.disk_percent}%\`}}/></div><p className="resource-foot">Réseau reçu {formatBytes(resources.system.network_received_bytes)} · envoyé {formatBytes(resources.system.network_sent_bytes)}</p></> : <p className="dash-empty">Chargement des métriques système…</p>}
            </article>
            <article className="dash-card"><div className="dash-heading"><h3><Clock3/> Activité récente</h3></div>
              {heartbeatRuns.slice(0,3).map(run=><div className="activity-line" key={run.id}><span className="activity-dot"></span><div><b>{run.summary || run.error || 'Cycle autonome'}</b><small>{run.status} · {run.started_at}</small></div></div>)}
              {objectives.slice(0,2).map(goal=><div className="activity-line" key={\`goal-\${goal.id}\`}><span className="activity-dot blue-dot"></span><div><b>Objectif · {goal.title}</b><small>{goal.completed_steps || 0}/{goal.total_steps || 0} étapes terminées</small></div></div>)}
              {!heartbeatRuns.length && !objectives.length && <p className="dash-empty">L’activité apparaîtra ici au fur et à mesure de l’exécution.</p>}
            </article>
            <article className="dash-card quick-actions"><div className="dash-heading"><h3><Zap/> Accès rapide</h3></div><button onClick={()=>setPage('agent')}><Bot/>Ouvrir l’agent</button><button onClick={()=>setPage('tasks')}><Play/>Nouvelle tâche</button><button onClick={()=>setPage('agents')}><Users/>Équipe multi-agents</button><button onClick={()=>setPage('resources')}><Gauge/>Surveiller les ressources</button></article>
          </section>
        </>}
\n        {page === 'agent' && <>
          <section className="metrics">
            <div className="metric"><Cpu /><div><small>FOURNISSEUR · MODÈLE</small><b>{provider} · {model}</b></div></div>
            <div className="metric"><Folder /><div><small>FICHIERS WORKSPACE</small><b>{workspace.length}</b></div></div>
            <div className="metric"><Activity /><div><small>ÉTAT</small><b>{busy ? 'Travail en cours' : 'En attente'}</b></div></div>
          </section>
          <section className="chat">
            <div className="chathead"><b>Conversation</b><span>Think → Act → Observe</span></div>
            <div className="messages">
              {messages.map((message, index) => <div className={`message ${message.role}`} key={index}><div className="avatar">{message.role === 'assistant' ? <Bot size={16} /> : 'VOUS'}</div><div className="bubble">{message.content}</div></div>)}
              {busy && <div className="working">Automaton réfléchit et agit…</div>}
            </div>
            <div className="composer">
              <textarea value={prompt} onChange={event => setPrompt(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void send(); } }} placeholder="Décris une tâche à réaliser…" rows={2} />
              <button onClick={() => void send()} disabled={busy || !prompt.trim()}><Send size={17} /></button>
            </div>
            <small className="hint">Entrée pour envoyer · Maj + Entrée pour une nouvelle ligne · Actions limitées au workspace</small>
          </section>
          <section className="workspace">
            <div className="chathead"><b><Folder size={15} /> Espace de travail</b><span>backend/workspace</span></div>
            {workspace.length ? workspace.map(file => <div className="file" key={file}>{file}</div>) : <p className="empty">Aucun fichier pour le moment.</p>}
          </section>
        </>}


        {page === 'tasks' && <section className="panel">
          <div className="panelintro"><ListTodo /><div><h2>File de tâches persistantes</h2><p>Les tâches sont enregistrées dans SQLite, exécutées une par une et remises en attente après un redémarrage du backend si elles étaient en cours.</p></div></div>
          <label>Nouvelle tâche<textarea rows={4} value={taskPrompt} onChange={e => setTaskPrompt(e.target.value)} placeholder="Décris une tâche à exécuter par Automaton…" /></label>
          <button className="primary" disabled={!taskPrompt.trim()} onClick={() => void enqueueTask()}><Play size={15} /> Ajouter à la file</button>
          <div className="tasktoolbar"><h3>Tâches ({tasks.length})</h3><button className="secondary" onClick={() => void refreshTasks()}>Actualiser</button></div>
          {tasks.length ? tasks.map(task => <article className="taskrow" key={task.id}>
            <div className="taskmeta"><b>#{task.id}</b><span className={`statuspill ${task.status}`}>{task.status}</span><small>{task.created_at}</small></div>
            <p>{task.prompt}</p>
            {task.result && <div className="taskoutput">{task.result}</div>}
            {task.error && <div className="taskerror">{task.error}</div>}
            {task.status === 'queued' && <button className="dangericon" onClick={() => void cancelTask(task.id)} title="Annuler la tâche"><Trash2 size={16} /></button>}
          </article>) : <p className="empty">La file est vide.</p>}
        </section>}


        {page === 'objectives' && <section className="panel">
          <div className="panelintro"><Target /><div><h2>Gestionnaire d'objectifs</h2><p>Définis une mission durable. Le superviseur évalue les preuves, détecte les blocages et peut ajouter des étapes correctives en conservant les versions précédentes du plan.</p></div></div>
          <label>Titre de l'objectif<input value={goalTitle} onChange={e=>setGoalTitle(e.target.value)} maxLength={160} placeholder="Ex. Préparer une version stable de mon application" /></label>
          <label>Description et critères de réussite<textarea rows={4} value={goalDescription} onChange={e=>setGoalDescription(e.target.value)} maxLength={4000} placeholder="Décris le résultat attendu, les contraintes et les critères de validation…" /></label>
          <label>Priorité<select value={goalPriority} onChange={e=>setGoalPriority(Number(e.target.value))}>{[1,2,3,4,5].map(n=><option key={n} value={n}>{n} / 5</option>)}</select></label>
          <button className="primary" disabled={busy || !goalTitle.trim() || !goalDescription.trim()} onClick={()=>void createObjective()}><Play size={15}/>{busy ? 'Planification…' : 'Créer et planifier'}</button>
          <div className="tasktoolbar"><h3>Objectifs enregistrés ({objectives.length})</h3><button className="secondary" onClick={()=>void refreshObjectives()}>Actualiser</button></div>
          {objectives.length ? objectives.map(goal=><article className="taskrow" key={goal.id}>
            <div className="taskmeta"><b>#{goal.id} · {goal.title}</b><span className={`statuspill ${goal.status}`}>{goal.status}</span><small>Priorité {goal.priority}/5 · {goal.completed_steps || 0}/{goal.total_steps || 0} étapes</small></div>
            <p>{goal.description}</p>
            <div className="progress"><div style={{width:`${goal.total_steps ? (goal.completed_steps/goal.total_steps)*100 : 0}%`}} /></div>
            <div className="supervisorbox">
              <b>Supervision : {goal.supervisor_state || 'monitoring'}</b>
              <small>{goal.supervisor_note || 'En attente de la première évaluation.'}</small>
              {goal.supervised_at && <small>Dernière évaluation : {goal.supervised_at}</small>}
            </div>
            <div className="tasktoolbar">
              <button className="secondary" onClick={()=>void superviseObjective(goal.id)}>Superviser maintenant</button>
              <button className="secondary" onClick={()=>void loadObjectiveHistory(goal.id)}>Historique</button>
              {goal.status==='active' && <button className="secondary" onClick={()=>void changeObjectiveStatus(goal.id,'paused')}>Mettre en pause</button>}
              {goal.status==='paused' && <button className="secondary" onClick={()=>void changeObjectiveStatus(goal.id,'active')}>Reprendre</button>}
              {(goal.status==='active'||goal.status==='paused') && <button className="dangericon" onClick={()=>void changeObjectiveStatus(goal.id,'cancelled')}>Annuler</button>}
            </div>
            {objectiveRevisions[goal.id]?.map(revision=><div className="revisionrow" key={revision.id}><b>Plan v{revision.revision} · {revision.reason}</b><small>{revision.created_at}</small><pre>{JSON.parse(revision.plan_json).map((step:{title:string;description:string},index:number)=>`${index+1}. ${step.title} — ${step.description}`).join('\n')}</pre></div>)}
            {objectiveEvents[goal.id]?.map(event=><div className="runrow" key={event.id}><span className="statuspill">{event.event_type}</span><div><b>{event.message}</b><small>{event.created_at}</small>{event.details && <small>{event.details}</small>}</div></div>)}
            {goal.steps?.map(step=><div className="runrow" key={step.id}><span className={`statuspill ${step.status}`}>{step.status}</span><div><b>{step.position}. {step.title}</b><small>{step.description}</small>{step.result && <small>Résultat : {step.result}</small>}{step.error && <small className="taskerror">{step.error}</small>}</div>{step.status==='failed' && <button className="secondary" onClick={()=>void retryObjectiveStep(goal.id,step.id)}>Relancer</button>}</div>)}
          </article>) : <p className="empty">Aucun objectif défini.</p>}
        </section>}

        {page === 'heartbeat' && <section className="panel">
          <div className="panelintro"><Activity /><div><h2>Cycles autonomes</h2><p>Le heartbeat lance périodiquement une tâche de contrôle dans le workspace.</p></div></div>
          {heartbeat && <>
            <label className="toggleline"><span><b>Activer le heartbeat</b><small>Désactivé par défaut au premier démarrage.</small></span><input type="checkbox" checked={!!heartbeat.enabled} onChange={e => setHeartbeat({ ...heartbeat, enabled: e.target.checked ? 1 : 0 })} /></label>
            <label>Intervalle (secondes)<input type="number" min={30} max={86400} value={heartbeat.interval_seconds} onChange={e => setHeartbeat({ ...heartbeat, interval_seconds: Number(e.target.value) })} /></label>
            <label>Consigne du cycle<textarea rows={4} value={heartbeat.prompt} onChange={e => setHeartbeat({ ...heartbeat, prompt: e.target.value })} /></label>
            <button className="primary" onClick={() => void saveHeartbeat()}>Enregistrer</button>
          </>}
          <h3>Historique des cycles</h3>
          {heartbeatRuns.length ? heartbeatRuns.map(run => <div className="runrow" key={run.id}><span className={`statuspill ${run.status}`}>{run.status}</span><div><b>{run.summary || run.error || 'Cycle lancé'}</b><small>{run.started_at}</small></div></div>) : <p className="empty">Aucun cycle enregistré.</p>}
        </section>}

        {page === 'memory' && <section className="panel">
          <div className="panelintro"><Brain /><div><h2>Souvenirs persistants</h2><p>Les souvenirs sont stockés dans SQLite et peuvent être rappelés par l’agent.</p></div></div>
          <label>Nouveau souvenir<textarea rows={3} value={memoryText} onChange={e => setMemoryText(e.target.value)} placeholder="Information à conserver entre les sessions…" /></label>
          <div className="formgrid"><label>Tags<input value={memoryTags} onChange={e => setMemoryTags(e.target.value)} placeholder="projet, préférence…" /></label><label>Importance<select value={importance} onChange={e => setImportance(Number(e.target.value))}>{[1,2,3,4,5].map(n => <option key={n} value={n}>{n} / 5</option>)}</select></label></div>
          <button className="primary" onClick={() => void saveMemory()} disabled={!memoryText.trim()}>Enregistrer le souvenir</button>
          <h3>Souvenirs enregistrés ({memories.length})</h3>
          {memories.length ? memories.map(item => <div className="memoryrow" key={item.id}><div><b>{item.content}</b><small>{item.tags || 'Sans tags'} · importance {item.importance} · {item.created_at}</small></div><button className="dangericon" onClick={() => void deleteMemory(item.id)} title="Supprimer"><Trash2 size={16} /></button></div>) : <p className="empty">Aucun souvenir enregistré.</p>}
        </section>}

        {page === 'resources' && <section className="panel">
          <div className="panelintro"><Gauge /><div><h2>État de la machine</h2><p>Informations d’exécution et inventaire limité au workspace.</p></div></div>
          {resources && <>
            <div className="resourcegrid">
              <div className="resourcecard"><small>FICHIERS</small><b>{resources.workspace.file_count}</b><span>{formatBytes(resources.workspace.total_bytes)} dans le workspace</span></div>
              <div className="resourcecard"><small>ESPACE LIBRE</small><b>{formatBytes(resources.storage.free_bytes)}</b><span>sur {formatBytes(resources.storage.total_bytes)}</span></div>
              <div className="resourcecard"><small>PROCESSUS API</small><b>{resources.pid}</b><span>Python {resources.python}</span></div>
            </div>
            <p className="subtle">{resources.platform}</p><h3>Fichiers du workspace</h3>
            {resources.workspace.files.map(file => <div className="file" key={file.path}><span>{file.path}</span><small>{formatBytes(file.size)}</small></div>)}
            <p className="securitynote"><ShieldCheck size={15} /> Aucun contrôle arbitraire des processus ; inventaire limité au workspace.</p>
          </>}
          <button className="secondary" onClick={() => void refreshResources()}>Actualiser les ressources</button>
        </section>}

        {page === 'agents' && <section className="panel">
          <div className="panelintro"><Users /><div><h2>Équipe spécialisée</h2><p>Trois rôles exécutés séquentiellement via le fournisseur IA configuré.</p></div></div>
          <div className="rolegrid"><div><b>01 · Planificateur</b><small>Décompose la tâche en étapes.</small></div><div><b>02 · Analyste</b><small>Identifie faits, risques et inconnues.</small></div><div><b>03 · Réviseur</b><small>Recherche erreurs et tests manquants.</small></div></div>
          <label>Tâche à déléguer<textarea rows={4} value={teamTask} onChange={e => setTeamTask(e.target.value)} placeholder="Décris une tâche à analyser par l'équipe…" /></label>
          <button className="primary" disabled={busy || !teamTask.trim()} onClick={() => void runTeam()}><Play size={15} /> {busy ? 'Agents au travail…' : 'Lancer l’équipe'}</button>
          {teamResult && <><h3>Résultats · {teamResult.mode}</h3>{Object.entries(teamResult.agents).map(([role, output]) => <article className="agentresult" key={role}><b>{role}</b><p>{output}</p></article>)}</>}
        </section>}

        {page === 'improvements' && <section className="panel">
          <div className="panelintro"><GitBranch /><div><h2>Application de patch Git</h2><p>Le moteur applique un diff unifié au backend local, compile le code et annule le patch si la compilation échoue.</p></div></div>
          <div className="warning"><ShieldCheck size={17} /><span>Fonction désactivée par défaut. Elle exige AUTO_IMPROVE_ENABLED=true, un dépôt Git propre et un patch limité à backend/app/. Le patch appliqué n’est pas automatiquement commité.</span></div>
          <label>Patch unifié<textarea className="patcharea" rows={15} value={patch} onChange={e => setPatch(e.target.value)} placeholder={'diff --git a/backend/app/... b/backend/app/...\n--- a/backend/app/...\n+++ b/backend/app/...'} /></label>
          <button className="primary" disabled={busy || !patch.trim()} onClick={() => void applyPatch()}><GitBranch size={15} /> {busy ? 'Validation…' : 'Valider et appliquer le patch'}</button>
        </section>}
        <footer><Zap size={13} /> Automaton · Exécution locale · Clés API conservées côté backend</footer>
      </main>
    </div>
  );
}

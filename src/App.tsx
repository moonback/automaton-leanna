import { Component, lazy, Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  Activity, Bot, Brain, Cpu, FileText, Folder, Gauge, GitBranch, ListTodo, Play, RefreshCw, RotateCcw, Search, Target,
  Send, ShieldCheck, Trash2, Users, X, Zap
} from 'lucide-react';
import type { SatelliteKind, SceneEventKind } from './Scene3D';

// Three.js is ~700 kB: load it after the UI so the first paint is not blocked.
const Scene3D = lazy(() => import('./Scene3D'));

/** The 3D layer is decorative: if it throws, drop it instead of unmounting the whole app. */
class SceneBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? <div className="scene" aria-hidden="true" /> : this.props.children; }
}

const API = 'http://127.0.0.1:8765';
type ToolStep = { tool: string; arguments?: Record<string, unknown>; success: boolean; error?: string };
type Message = { role: 'user' | 'assistant'; content: string; trace?: ToolStep[] };
type Summary = { tasks_queued: number; tasks_running: number; tasks_failed: number; tasks_succeeded: number; objectives_active: number; processes_running: number };
type TaskFilter = 'all' | 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';
const HISTORY_SAMPLES = 60;

/** Inline SVG trend line for the last samples (0..100 %). */
function Sparkline({ values, label }: { values: number[]; label: string }) {
  if (values.length < 2) return null;
  const points = values.map((value, index) => `${(index / (HISTORY_SAMPLES - 1)) * 100},${30 - (Math.min(value, 100) / 100) * 30}`).join(' ');
  return <svg className="sparkline" viewBox="0 0 100 30" preserveAspectRatio="none" role="img" aria-label={label}><polyline points={points} /></svg>;
}
type Page = 'agent' | 'tasks' | 'objectives' | 'heartbeat' | 'memory' | 'resources' | 'processes' | 'agents' | 'improvements';
type Memory = { id: number; content: string; tags: string; importance: number; created_at: string };
type HeartbeatRun = { id: number; status: string; summary: string; error: string; started_at: string };
type HeartbeatConfig = { enabled: number; interval_seconds: number; prompt: string };
type ResourceSettings = { cpu_warning: number; memory_warning: number; disk_warning: number };
type ResourceSnapshot = {
  platform: string; python: string; pid: number; sampled_at: string;
  cpu: { percent: number; logical_cores: number | null; physical_cores: number | null };
  memory: { total_bytes: number; available_bytes: number; used_bytes: number; percent: number };
  storage: { total_bytes: number; free_bytes: number; used_bytes: number; percent: number };
  network: { bytes_sent: number; bytes_received: number; packets_sent: number; packets_received: number } | null;
  gpu: { available: boolean; reason: string };
  processes: { pid: number; name: string; cpu_percent: number; memory_percent: number; memory_bytes: number }[];
  alerts: { metric: string; value: number; threshold: number; message: string }[];
  settings: ResourceSettings;
  workspace: { file_count: number; total_bytes: number; files: { path: string; size: number }[] };
};
type AgentResult = { mode: string; agents: Record<string, string> };
type Objective = { id:number; title:string; description:string; status:string; priority:number; total_steps:number; completed_steps:number; supervisor_state?:string; supervisor_note?:string; supervised_at?:string; steps?: {id:number;position:number;title:string;description:string;status:string;result:string;error:string}[] };
type Task = { id: number; prompt: string; status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'; result: string; error: string; created_at: string; updated_at: string };
type ManagedProcess = { id:number; pid:number; script:string; status:string; exit_code:number|null; started_at:string; updated_at:string; stopped_at:string|null; isolation:string; isolation_profile:string; security_boundary:string };

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
  const [page, setPage] = useState<Page>('agent');
  const [messages, setMessages] = useState<Message[]>([{ role: 'assistant', content: 'Automaton est prêt. Décris une tâche à accomplir dans son espace de travail.' }]);
  const [prompt, setPrompt] = useState('');
  const [taskPrompt, setTaskPrompt] = useState('');
  const [tasks, setTasks] = useState<Task[]>([]);
  const [managedProcesses, setManagedProcesses] = useState<ManagedProcess[]>([]);
  const [processPath, setProcessPath] = useState('');
  const [processIsolation, setProcessIsolation] = useState<'job_object'|'windows_sandbox'>('windows_sandbox');
  const [selectedProcess, setSelectedProcess] = useState<number | null>(null);
  const [processLog, setProcessLog] = useState('');
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
  const [resourceSettings, setResourceSettings] = useState<ResourceSettings>({ cpu_warning: 85, memory_warning: 85, disk_warning: 90 });
  const [teamTask, setTeamTask] = useState('');
  const [teamResult, setTeamResult] = useState<AgentResult | null>(null);
  const [patch, setPatch] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [summary, setSummary] = useState<Summary | null>(null);
  const [preview, setPreview] = useState<{ path: string; content: string } | null>(null);
  const [taskFilter, setTaskFilter] = useState<TaskFilter>('all');
  const [memoryQuery, setMemoryQuery] = useState('');
  const [samples, setSamples] = useState<{ cpu: number[]; memory: number[] }>({ cpu: [], memory: [] });
  const [patchDiff, setPatchDiff] = useState('');
  const [sceneEvent, setSceneEvent] = useState<{ seq: number; kind: SceneEventKind } | null>(null);
  const fireSceneEvent = (kind: SceneEventKind) => setSceneEvent(current => ({ seq: (current?.seq ?? 0) + 1, kind }));
  const previousSummary = useRef<Summary | null>(null);
  // Task results show up as counter increases between two polls.
  useEffect(() => {
    const before = previousSummary.current;
    previousSummary.current = summary;
    if (!before || !summary) return;
    if (summary.tasks_failed > before.tasks_failed) fireSceneEvent('failure');
    else if (summary.tasks_succeeded > before.tasks_succeeded) fireSceneEvent('success');
  }, [summary]);

  async function refreshBase() {
    try {
      const [health, files, counts] = await Promise.all([
        request<{ status: string; version: string }>('/health'),
        request<{ files: string[] }>('/workspace'),
        request<Summary>('/summary')
      ]);
      setStatus(`Connecté · API ${health.version}`);
      setWorkspace(files.files || []);
      setSummary(counts);
    } catch { setStatus('Backend indisponible'); }
  }
  async function refreshConfig() {
    const config = await request<{ provider: string; model: string }>('/config');
    setProvider(config.provider); setModel(config.model);
  }
  async function refreshHeartbeat() {
    const data = await request<{ config: HeartbeatConfig; runs: HeartbeatRun[] }>('/heartbeat');
    setHeartbeat(data.config); setHeartbeatRuns(data.runs);
  }
  async function refreshMemories(query = memoryQuery) {
    const data = await request<{ memories: Memory[] }>(`/memory?q=${encodeURIComponent(query.trim())}&limit=100`);
    setMemories(data.memories);
  }
  async function refreshResources() {
    const [snapshot, settings] = await Promise.all([request<ResourceSnapshot>('/resources'), request<ResourceSettings>('/resources/settings')]);
    setResources(snapshot); setResourceSettings(settings);
    setSamples(current => ({
      cpu: [...current.cpu, snapshot.cpu.percent].slice(-HISTORY_SAMPLES),
      memory: [...current.memory, snapshot.memory.percent].slice(-HISTORY_SAMPLES)
    }));
  }
  async function refreshTasks() { const data = await request<{ tasks: Task[] }>('/tasks'); setTasks(data.tasks); }
  async function refreshProcesses() { const data = await request<{ processes: ManagedProcess[] }>('/processes'); setManagedProcesses(data.processes); }
  async function refreshObjectives() { const data = await request<{ objectives: Objective[] }>('/objectives'); const details = await Promise.all(data.objectives.map(item => request<Objective>(`/objectives/${item.id}`))); setObjectives(details); }
  async function refreshAll() {
    setError('');
    await refreshBase();
    try { await Promise.all([refreshConfig(), refreshHeartbeat(), refreshMemories(), refreshResources(), refreshTasks(), refreshObjectives(), refreshProcesses()]); }
    catch (e) { setError(e instanceof Error ? e.message : 'Erreur de chargement'); }
  }
  useEffect(() => {
    void refreshAll();
    // Restore the conversation kept by the backend instead of starting from an empty chat.
    request<{ messages: Message[] }>('/history')
      .then(data => { if (data.messages.length) setMessages(data.messages); })
      .catch(() => {});
  }, []);
  useEffect(() => {
    if (!notice) return;
    const id = window.setTimeout(() => setNotice(''), 5000);
    return () => window.clearTimeout(id);
  }, [notice]);
  useEffect(() => {
    const id = window.setTimeout(() => { void refreshMemories(memoryQuery).catch(() => {}); }, 250);
    return () => window.clearTimeout(id);
  }, [memoryQuery]);
  useEffect(() => {
    if (!preview) return;
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') setPreview(null); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [preview]);
  // Poll only the data the visible page renders, and nothing while the window is hidden.
  useEffect(() => {
    const byPage: Partial<Record<Page, () => Promise<void>>> = { resources: refreshResources, tasks: refreshTasks, objectives: refreshObjectives, processes: refreshProcesses };
    const tick = () => { if (document.hidden) return; void refreshBase(); void byPage[page]?.().catch(() => {}); };
    tick();
    const id = window.setInterval(tick, 3000);
    return () => window.clearInterval(id);
  }, [page]);

  async function send() {
    const value = prompt.trim();
    if (!value || busy) return;
    setMessages(current => [...current, { role: 'user', content: value }]);
    setPrompt(''); setBusy(true); setError('');
    try {
      const data = await request<{ answer: string; tool_trace?: ToolStep[] }>('/agent/run', { method: 'POST', body: JSON.stringify({ prompt: value }) });
      setMessages(current => [...current, { role: 'assistant', content: data.answer || 'Tâche terminée.', trace: data.tool_trace }]);
      fireSceneEvent('reply');
      void refreshBase();
    } catch (e) {
      setMessages(current => [...current, { role: 'assistant', content: `Erreur : ${e instanceof Error ? e.message : 'Erreur inconnue'}` }]);
      fireSceneEvent('failure');
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
  async function requeueTask(task: Task) {
    try {
      const created = await request<Task>('/tasks', { method: 'POST', body: JSON.stringify({ prompt: task.prompt }) });
      await refreshTasks(); setNotice(`Tâche #${task.id} remise en file sous le numéro #${created.id}.`);
    } catch (e) { setError(e instanceof Error ? e.message : 'Remise en file impossible'); }
  }
  async function openFile(path: string) {
    try { setPreview(await request<{ path: string; content: string }>(`/workspace/file?path=${encodeURIComponent(path)}`)); }
    catch (e) { setError(e instanceof Error ? e.message : 'Lecture impossible'); }
  }

  async function startManagedProcess() {
    const path = processPath.trim();
    if (!path) return;
    setError(''); setNotice('');
    try {
      const item = await request<ManagedProcess>('/processes', { method:'POST', body:JSON.stringify({path, isolation:processIsolation}) });
      setProcessPath('');
      setSelectedProcess(item.id);
      await refreshProcesses();
      setNotice(`Processus #${item.id} démarré (PID hôte ${item.pid}, ${item.isolation_profile}).`);
    } catch (e) { setError(e instanceof Error ? e.message : 'Démarrage impossible'); }
  }
  async function stopManagedProcess(id:number) {
    if (!window.confirm(`Arrêter le processus #${id} et ses enfants ?`)) return;
    try {
      await request(`/processes/${id}`, {method:'DELETE'});
      await refreshProcesses();
      if (selectedProcess === id) await loadProcessLog(id);
      setNotice(`Demande d'arrêt envoyée au processus #${id}.`);
    } catch (e) { setError(e instanceof Error ? e.message : 'Arrêt impossible'); }
  }
  async function loadProcessLog(id:number) {
    try {
      const data = await request<{process:ManagedProcess;log:string}>(`/processes/${id}/logs`);
      setSelectedProcess(id); setProcessLog(data.log || '');
    } catch (e) { setError(e instanceof Error ? e.message : 'Journal indisponible'); }
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
  async function saveResourceSettings() {
    try {
      const saved = await request<ResourceSettings>('/resources/settings', { method: 'PUT', body: JSON.stringify(resourceSettings) });
      setResourceSettings(saved);
      await refreshResources();
      setNotice('Seuils de ressources enregistrés.');
    } catch (e) { setError(e instanceof Error ? e.message : 'Enregistrement des seuils impossible'); }
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
      setPatchDiff(result.diff);
    } catch (e) { setError(e instanceof Error ? e.message : 'Patch refusé'); }
    finally { setBusy(false); }
  }

  const nav: { id: Page; label: string; icon: typeof Bot }[] = [
    { id: 'agent', label: 'Agent', icon: Bot },
    { id: 'tasks', label: 'File de tâches', icon: ListTodo },
    { id: 'objectives', label: 'Objectifs', icon: Target },
    { id: 'heartbeat', label: 'Heartbeat', icon: Activity },
    { id: 'memory', label: 'Mémoire', icon: Brain },
    { id: 'resources', label: 'Ressources', icon: Gauge },
    { id: 'processes', label: 'Processus', icon: Cpu },
    { id: 'agents', label: 'Multi-agents', icon: Users },
    { id: 'improvements', label: 'Auto-amélioration', icon: GitBranch }
  ];
  const titles: Record<Page, string> = {
    agent: 'Agent', tasks: 'File de tâches persistantes', objectives: 'Objectifs autonomes', heartbeat: 'Heartbeat', memory: 'Mémoire persistante',
    resources: 'Gestionnaire de ressources', processes: 'Gestionnaire de processus', agents: 'Équipe multi-agents',
    improvements: 'Auto-amélioration'
  };

  const connected = status.startsWith('Connecté');
  const queuedWork = (summary?.tasks_queued ?? 0) + (summary?.tasks_running ?? 0);
  const objectivesActive = summary?.objectives_active ?? 0;
  const processesRunning = summary?.processes_running ?? 0;
  const satelliteKey = `${processesRunning}/${queuedWork}/${objectivesActive}`;
  const sceneState = useMemo(() => ({
    page, busy, connected,
    load: Math.min(1, ((summary?.tasks_running ?? 0) + processesRunning) / 4),
    satellites: [
      ...Array<SatelliteKind>(Math.min(processesRunning, 8)).fill('process'),
      ...Array<SatelliteKind>(Math.min(queuedWork, 8)).fill('task'),
      ...Array<SatelliteKind>(Math.min(objectivesActive, 8)).fill('objective')
    ],
    event: sceneEvent
  }), [page, busy, connected, satelliteKey, summary?.tasks_running, sceneEvent]);
  const badges: Partial<Record<Page, number>> = { tasks: queuedWork, objectives: objectivesActive, processes: processesRunning };
  const coreLine = !connected ? 'Backend injoignable' : busy ? 'Automaton travaille' : queuedWork ? 'Automaton traite la file' : 'Automaton est en veille';
  const taskCounts = tasks.reduce<Record<string, number>>((acc, task) => ({ ...acc, [task.status]: (acc[task.status] ?? 0) + 1 }), {});
  const visibleTasks = taskFilter === 'all' ? tasks : tasks.filter(task => task.status === taskFilter);
  const taskFilters: { id: TaskFilter; label: string }[] = [
    { id: 'all', label: 'Toutes' }, { id: 'queued', label: 'En attente' }, { id: 'running', label: 'En cours' },
    { id: 'succeeded', label: 'Réussies' }, { id: 'failed', label: 'Échouées' }, { id: 'cancelled', label: 'Annulées' }
  ];

  return (
    <>
    <SceneBoundary><Suspense fallback={<div className="scene" aria-hidden="true" />}><Scene3D state={sceneState} /></Suspense></SceneBoundary>
    <div className="shell">
      <aside className="sidebar">
        <div className="brand"><div className="logo"><Bot /></div><div><b>Automaton</b><small>Agent local v1.4.0</small></div></div>
        <nav className="navgroup">{nav.map(item => {
          const Icon = item.icon;
          const badge = badges[item.id];
          return <button key={item.id} className={`nav ${page === item.id ? 'active' : ''}`} aria-current={page === item.id ? 'page' : undefined} onClick={() => { setPage(item.id); setError(''); setNotice(''); }}>
            <Icon size={17} />{item.label}{badge ? <span className="badge" aria-label={`${badge} actifs`}>{badge}</span> : null}
          </button>;
        })}</nav>
        <div className="sidebottom"><span className={`dot ${connected ? 'ok' : ''}`} />{status}</div>
      </aside>
      <main>
        <header><div><h1 key={page}>{titles[page]}</h1><p>{provider} / {model}</p></div><button className="iconbtn" onClick={() => void refreshAll()} title="Actualiser" aria-label="Actualiser"><RefreshCw size={17} /></button></header>
        {error && <div className="alert error" role="alert">{error}</div>}
        {notice && <div className="alert success" role="status">{notice}</div>}

        {page === 'agent' && <>
          <section className="core-hero" aria-live="polite">
            <p className="core-state">{coreLine}</p>
            <div className="core-legend">
              <span><i className="swatch task" />{queuedWork} {queuedWork > 1 ? 'tâches' : 'tâche'} en file</span>
              <span><i className="swatch objective" />{objectivesActive} {objectivesActive > 1 ? 'objectifs actifs' : 'objectif actif'}</span>
              <span><i className="swatch process" />{processesRunning} processus en cours</span>
            </div>
          </section>
          <section className="chat">
            <div className="chathead"><b>Conversation</b><span>{messages.filter(m => m.role === 'user').length} demandes</span></div>
            <div className="messages">
              {messages.map((message, index) => <div className={`message ${message.role}`} key={index}><div className="avatar">{message.role === 'assistant' ? <Bot size={16} /> : 'Vous'}</div><div className="bubble">{message.content}
                {message.trace && message.trace.length > 0 && <details className="trace"><summary>{message.trace.length} {message.trace.length > 1 ? 'actions exécutées' : 'action exécutée'}</summary>
                  <ol>{message.trace.map((step, stepIndex) => <li key={stepIndex} className={step.success ? 'ok' : 'ko'}><b>{step.tool}</b>{step.arguments && Object.keys(step.arguments).length > 0 && <code>{JSON.stringify(step.arguments).slice(0, 160)}</code>}{step.error && <small>{step.error}</small>}</li>)}</ol>
                </details>}
              </div></div>)}
              {busy && <div className="working">Automaton réfléchit et agit…</div>}
            </div>
            <div className="composer">
              <textarea value={prompt} onChange={event => setPrompt(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void send(); } }} placeholder="Décris une tâche à réaliser…" rows={2} />
              <button onClick={() => void send()} disabled={busy || !prompt.trim()} aria-label="Envoyer"><Send size={17} /></button>
            </div>
            <small className="hint">Entrée pour envoyer, Maj + Entrée pour aller à la ligne. L'agent n'agit que dans le workspace.</small>
          </section>
          <section className="workspace">
            <div className="chathead"><b><Folder size={15} /> Espace de travail</b><span>{workspace.length} fichiers</span></div>
            {workspace.length ? workspace.map(file => <button className="file filebtn" key={file} onClick={() => void openFile(file)}><span><FileText size={13} /> {file}</span><small>Ouvrir</small></button>) : <p className="empty">Aucun fichier pour le moment. Demande à l'agent d'en créer un.</p>}
          </section>
        </>}


        {page === 'tasks' && <section className="panel">
          <div className="panelintro"><ListTodo /><div><h2>File de tâches persistantes</h2><p>Les tâches sont enregistrées dans SQLite, exécutées une par une et remises en attente après un redémarrage du backend si elles étaient en cours.</p></div></div>
          <label>Nouvelle tâche<textarea rows={4} value={taskPrompt} onChange={e => setTaskPrompt(e.target.value)} placeholder="Décris une tâche à exécuter par Automaton…" /></label>
          <button className="primary" disabled={!taskPrompt.trim()} onClick={() => void enqueueTask()}><Play size={15} /> Ajouter à la file</button>
          <div className="tasktoolbar"><h3>Tâches ({tasks.length})</h3><button className="secondary" onClick={() => void refreshTasks()}>Actualiser</button></div>
          <div className="chips" role="group" aria-label="Filtrer par état">{taskFilters.map(filter => <button key={filter.id} className={`chip ${taskFilter === filter.id ? 'on' : ''}`} aria-pressed={taskFilter === filter.id} onClick={() => setTaskFilter(filter.id)}>{filter.label}<span>{filter.id === 'all' ? tasks.length : taskCounts[filter.id] ?? 0}</span></button>)}</div>
          {visibleTasks.length ? visibleTasks.map(task => <article className="taskrow" key={task.id}>
            <div className="taskmeta"><b>#{task.id}</b><span className={`statuspill ${task.status}`}>{task.status}</span><small>{task.created_at}</small></div>
            <p>{task.prompt}</p>
            {task.result && <div className="taskoutput">{task.result}</div>}
            {task.error && <div className="taskerror">{task.error}</div>}
            {task.status === 'queued' && <button className="dangericon" onClick={() => void cancelTask(task.id)} title="Annuler la tâche" aria-label={`Annuler la tâche ${task.id}`}><Trash2 size={16} /></button>}
            {(task.status === 'failed' || task.status === 'cancelled') && <button className="secondary" onClick={() => void requeueTask(task)}><RotateCcw size={13} /> Remettre en file</button>}
          </article>) : <p className="empty">{tasks.length ? 'Aucune tâche dans cet état.' : 'La file est vide. Ajoute une tâche ci-dessus.'}</p>}
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
            {goal.steps && goal.steps.length > 0 && <details className="steps" open={goal.steps.some(step=>step.status==='failed')}>
              <summary>Étapes du plan ({goal.completed_steps || 0}/{goal.total_steps || 0})</summary>
              {goal.steps.map(step=><div className="runrow" key={step.id}><span className={`statuspill ${step.status}`}>{step.status}</span><div><b>{step.position}. {step.title}</b><small>{step.description}</small>{step.result && <small>Résultat : {step.result}</small>}{step.error && <small className="taskerror">{step.error}</small>}</div>{step.status==='failed' && <button className="secondary" onClick={()=>void retryObjectiveStep(goal.id,step.id)}>Relancer</button>}</div>)}
            </details>}
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
          <div className="tasktoolbar"><h3>Souvenirs enregistrés ({memories.length})</h3>
            <label className="searchfield"><Search size={14} /><input type="search" value={memoryQuery} onChange={e => setMemoryQuery(e.target.value)} placeholder="Rechercher dans le contenu ou les tags" aria-label="Rechercher un souvenir" /></label>
          </div>
          {memories.length ? memories.map(item => <div className="memoryrow" key={item.id}><span className="importance" aria-label={`Importance ${item.importance} sur 5`}>{'●'.repeat(item.importance)}<i>{'●'.repeat(5 - item.importance)}</i></span><div><b>{item.content}</b><small>{item.tags || 'Sans tags'} · {item.created_at}</small></div><button className="dangericon" onClick={() => void deleteMemory(item.id)} title="Supprimer" aria-label={`Supprimer le souvenir ${item.id}`}><Trash2 size={16} /></button></div>) : <p className="empty">{memoryQuery.trim() ? 'Aucun souvenir ne correspond à cette recherche.' : 'Aucun souvenir enregistré.'}</p>}
        </section>}

        {page === 'resources' && <section className="panel">
          <div className="panelintro"><Gauge /><div><h2>Supervision des ressources</h2><p>Mesures système actualisées toutes les 3 secondes. La collecte est en lecture seule.</p></div></div>
          {resources && <>
            {resources.alerts.length > 0 && <div className="warning"><Activity size={17} /><span>{resources.alerts.map(alert => alert.message).join(' · ')}</span></div>}
            <div className="resourcegrid">
              <div className="resourcecard"><small>Processeur, {resources.cpu.logical_cores ?? '?'} cœurs logiques</small><b>{resources.cpu.percent.toFixed(1)} %</b><span>Tendance des 3 dernières minutes</span><Sparkline values={samples.cpu} label="Historique CPU" /></div>
              <div className="resourcecard"><small>Mémoire vive</small><b>{resources.memory.percent.toFixed(1)} %</b><span>{formatBytes(resources.memory.used_bytes)} sur {formatBytes(resources.memory.total_bytes)}</span><Sparkline values={samples.memory} label="Historique RAM" /></div>
              <div className="resourcecard"><small>Disque des données</small><b>{resources.storage.percent.toFixed(1)} %</b><span>{formatBytes(resources.storage.free_bytes)} libres sur {formatBytes(resources.storage.total_bytes)}</span><progress max="100" value={resources.storage.percent} /></div>
              <div className="resourcecard"><small>Fichiers du workspace</small><b>{resources.workspace.file_count}</b><span>{formatBytes(resources.workspace.total_bytes)} au total</span></div>
            </div>
            <h3>Trafic réseau cumulé depuis le démarrage</h3>
            {resources.network ? <div className="resourcegrid">
              <div className="resourcecard"><small>Envoyé</small><b>{formatBytes(resources.network.bytes_sent)}</b><span>{resources.network.packets_sent.toLocaleString('fr-FR')} paquets</span></div>
              <div className="resourcecard"><small>Reçu</small><b>{formatBytes(resources.network.bytes_received)}</b><span>{resources.network.packets_received.toLocaleString('fr-FR')} paquets</span></div>
            </div> : <p className="empty">Compteurs réseau indisponibles.</p>}
            <h3>Seuils d'alerte</h3>
            <div className="formgrid">
              <label>CPU (%)<input type="number" min="1" max="100" value={resourceSettings.cpu_warning} onChange={e=>setResourceSettings({...resourceSettings,cpu_warning:Number(e.target.value)})} /></label>
              <label>RAM (%)<input type="number" min="1" max="100" value={resourceSettings.memory_warning} onChange={e=>setResourceSettings({...resourceSettings,memory_warning:Number(e.target.value)})} /></label>
              <label>Disque (%)<input type="number" min="1" max="100" value={resourceSettings.disk_warning} onChange={e=>setResourceSettings({...resourceSettings,disk_warning:Number(e.target.value)})} /></label>
            </div>
            <button className="secondary" onClick={()=>void saveResourceSettings()}>Enregistrer les seuils</button>
            <h3>Processus les plus consommateurs de mémoire</h3>
            {resources.processes.map(proc=><div className="file" key={proc.pid}><span>{proc.name} · PID {proc.pid}<small>CPU {proc.cpu_percent.toFixed(1)} % · RAM {proc.memory_percent.toFixed(1)} %</small></span><b>{formatBytes(proc.memory_bytes)}</b></div>)}
            <h3>Inventaire du workspace</h3>
            {resources.workspace.files.map(file => <div className="file" key={file.path}><span>{file.path}</span><small>{formatBytes(file.size)}</small></div>)}
            <p className="subtle">{resources.platform} · Python {resources.python} · PID backend {resources.pid} · Mesure {new Date(resources.sampled_at).toLocaleTimeString('fr-FR')}</p>
            <p className="securitynote"><ShieldCheck size={15} /> GPU non mesuré. Les processus affichés sont informatifs : Automaton ne contrôle pas arbitrairement les processus du système.</p>
          </>}
          <button className="secondary" onClick={() => void refreshResources()}>Actualiser les ressources</button>
        </section>}


        {page === 'processes' && <section className="panel">
          <div className="panelintro"><Cpu /><div><h2>Processus gérés par Automaton</h2><p>Démarre uniquement des scripts Python déjà présents dans le workspace. Les processus, PID, états et journaux sont suivis dans SQLite.</p></div></div>
          <div className="warning"><ShieldCheck size={17} /><span>Windows Sandbox fournit une isolation système plus forte : réseau, presse-papiers et vGPU désactivés ; dossier du script et runtime Python en lecture seule ; seul un dossier de journaux dédié est accessible en écriture. Windows Sandbox doit être activé sur Windows Pro/Entreprise/Éducation. Le profil Job Object reste disponible comme mode de compatibilité et ne bloque pas les accès fichiers/réseau du compte.</span></div>
          <label>Script Python du workspace<input list="workspace-scripts" value={processPath} onChange={e=>setProcessPath(e.target.value)} placeholder={workspace.find(file => file.endsWith('.py')) ?? 'workers/worker.py'} /></label>
          <datalist id="workspace-scripts">{workspace.filter(file => file.endsWith('.py')).map(file => <option key={file} value={file} />)}</datalist>
          <label>Profil d'isolation<select value={processIsolation} onChange={e=>setProcessIsolation(e.target.value as 'job_object'|'windows_sandbox')}><option value="windows_sandbox">Windows Sandbox · isolation renforcée</option><option value="job_object">Job Object · limites de ressources</option></select></label>
          <button className="primary" disabled={!processPath.trim()} onClick={()=>void startManagedProcess()}><Play size={15}/> Démarrer le processus</button>
          <div className="tasktoolbar"><h3>Processus suivis ({managedProcesses.length})</h3><button className="secondary" onClick={()=>void refreshProcesses()}>Actualiser</button></div>
          {managedProcesses.length ? managedProcesses.map(item=><article className="taskrow" key={item.id}>
            <div className="taskmeta"><b>#{item.id} · PID hôte {item.pid}</b><span className={`statuspill ${item.status}`}>{item.status}</span><small>{item.isolation_profile} · {item.security_boundary}</small></div>
            <p>{item.script}</p>
            <small className="processmeta">Démarré : {item.started_at} · Code de sortie : {item.exit_code ?? '—'}</small>
            <div className="tasktoolbar">
              <button className="secondary" onClick={()=>void loadProcessLog(item.id)}>Voir les journaux</button>
              {item.status === 'running' || item.status === 'stopping' ? <button className="dangericon" onClick={()=>void stopManagedProcess(item.id)}>Arrêter</button> : null}
            </div>
          </article>) : <p className="empty">Aucun processus géré.</p>}
          {selectedProcess !== null && <section className="processlogs"><div className="tasktoolbar"><h3>Journal · processus #{selectedProcess}</h3><button className="secondary" onClick={()=>void loadProcessLog(selectedProcess)}>Recharger</button></div><pre>{processLog || 'Aucune sortie enregistrée.'}</pre></section>}
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
          {patchDiff && <><h3>Fichiers modifiés par le dernier patch</h3><pre className="diffstat">{patchDiff}</pre></>}
        </section>}
        <footer><Zap size={13} /> Exécution locale. Les clés API restent dans le backend.</footer>
      </main>
    </div>
    {preview && <div className="drawer-backdrop" onClick={() => setPreview(null)}>
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={`Aperçu de ${preview.path}`} onClick={event => event.stopPropagation()}>
        <div className="chathead"><b><FileText size={15} /> {preview.path}</b><button className="iconbtn" onClick={() => setPreview(null)} aria-label="Fermer l'aperçu" autoFocus><X size={16} /></button></div>
        <pre>{preview.content || 'Fichier vide.'}</pre>
      </aside>
    </div>}
    </>
  );
}

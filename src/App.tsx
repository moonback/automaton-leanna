import { useEffect, useState } from 'react';
import {
  Activity, Bot, Brain, Cpu, Folder, Gauge, GitBranch, Play, RefreshCw,
  Send, Settings, ShieldCheck, Trash2, Users, Zap
} from 'lucide-react';

const API = 'http://127.0.0.1:8765';
type Message = { role: 'user' | 'assistant'; content: string };
type Page = 'agent' | 'heartbeat' | 'memory' | 'resources' | 'agents' | 'improvements';
type Memory = { id: number; content: string; tags: string; importance: number; created_at: string };
type HeartbeatRun = { id: number; status: string; summary: string; error: string; started_at: string };
type HeartbeatConfig = { enabled: number; interval_seconds: number; prompt: string };
type ResourceSnapshot = {
  platform: string; python: string; pid: number;
  workspace: { file_count: number; total_bytes: number; files: { path: string; size: number }[] };
  storage: { total_bytes: number; free_bytes: number };
};
type AgentResult = { mode: string; agents: Record<string, string> };

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
  async function refreshAll() {
    setError('');
    await refreshBase();
    try { await Promise.all([refreshHeartbeat(), refreshMemories(), refreshResources()]); }
    catch (e) { setError(e instanceof Error ? e.message : 'Erreur de chargement'); }
  }
  useEffect(() => {
    void refreshAll();
    const id = window.setInterval(() => { void refreshBase(); }, 15000);
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
    { id: 'agent', label: 'Agent', icon: Bot },
    { id: 'heartbeat', label: 'Heartbeat', icon: Activity },
    { id: 'memory', label: 'Mémoire', icon: Brain },
    { id: 'resources', label: 'Ressources', icon: Gauge },
    { id: 'agents', label: 'Multi-agents', icon: Users },
    { id: 'improvements', label: 'Auto-amélioration', icon: GitBranch }
  ];
  const titles: Record<Page, string> = {
    agent: 'Agent', heartbeat: 'Heartbeat', memory: 'Mémoire persistante',
    resources: 'Gestionnaire de ressources', agents: 'Équipe multi-agents',
    improvements: 'Auto-amélioration'
  };

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand"><div className="logo"><Bot /></div><div><b>Automaton</b><small>LOCAL AGENT · 0.4.0</small></div></div>
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

        {page === 'agent' && <>
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

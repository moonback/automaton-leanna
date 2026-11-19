import { useEffect, useState } from 'react';
import { Bot, Cpu, Folder, Send, Activity, Settings, RefreshCw } from 'lucide-react';

const API = 'http://127.0.0.1:8765';
type Message = { role: 'user' | 'assistant'; content: string };
type PublicConfig = { provider: string; model: string };

export default function App() {
  const [messages, setMessages] = useState<Message[]>([{ role: 'assistant', content: 'Automaton est prêt. Décris une tâche à accomplir dans son espace de travail.' }]);
  const [prompt, setPrompt] = useState('');
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('Connexion…');
  const [workspace, setWorkspace] = useState<string[]>([]);
  const [provider, setProvider] = useState('openrouter');
  const [model, setModel] = useState('chargement…');

  async function refresh() {
    try {
      const [health, files, config] = await Promise.all([
        fetch(`${API}/health`), fetch(`${API}/workspace`), fetch(`${API}/config`)
      ]);
      if (!health.ok || !files.ok || !config.ok) throw new Error('Backend indisponible');
      const [fileData, configData] = await Promise.all([files.json(), config.json()]) as [{ files: string[] }, PublicConfig];
      setStatus('Backend connecté');
      setWorkspace(fileData.files || []);
      setProvider(configData.provider);
      setModel(configData.model);
    } catch {
      setStatus('Backend indisponible');
    }
  }

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 10000);
    return () => clearInterval(id);
  }, []);

  async function send() {
    const value = prompt.trim();
    if (!value || busy) return;
    setMessages(current => [...current, { role: 'user', content: value }]);
    setPrompt('');
    setBusy(true);
    try {
      const response = await fetch(`${API}/agent/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: value })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Erreur backend');
      setMessages(current => [...current, { role: 'assistant', content: data.answer || 'Tâche terminée.' }]);
      refresh();
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Erreur inconnue';
      setMessages(current => [...current, { role: 'assistant', content: `Erreur : ${message}` }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand"><div className="logo"><Bot /></div><div><b>Automaton</b><small>LOCAL AGENT · 0.2.0</small></div></div>
        <div className="nav active"><Activity size={17} /> Agent</div>
        <div className="nav"><Folder size={17} /> Workspace</div>
        <div className="nav"><Settings size={17} /> Paramètres</div>
        <div className="sidebottom"><span className={`dot ${status === 'Backend connecté' ? 'ok' : ''}`} />{status}</div>
      </aside>
      <main>
        <header><div><h1>Agent</h1><p>Orchestration locale et exécution de tâches</p></div><button className="iconbtn" onClick={refresh}><RefreshCw size={17} /></button></header>
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
            <textarea value={prompt} onChange={event => setPrompt(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); send(); } }} placeholder="Décris une tâche à réaliser…" rows={2} />
            <button onClick={send} disabled={busy || !prompt.trim()}><Send size={17} /></button>
          </div>
          <small className="hint">Entrée pour envoyer · Maj + Entrée pour une nouvelle ligne · Actions limitées au workspace</small>
        </section>
        <section className="workspace">
          <div className="chathead"><b><Folder size={15} /> Espace de travail</b><span>backend/workspace</span></div>
          {workspace.length ? workspace.map(file => <div className="file" key={file}>{file}</div>) : <p className="empty">Aucun fichier pour le moment.</p>}
        </section>
      </main>
    </div>
  );
}

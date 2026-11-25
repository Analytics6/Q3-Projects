"use client";

import { FormEvent, KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  Activity, ArrowDown, ArrowUpRight, BadgeCheck, Banknote, BookOpen, Check, ChevronDown,
  CircleHelp, Clock3, Database, FileClock, FilePlus2, FileText, Gauge, Headphones,
  LayoutDashboard, LogOut, MessageCircle, MoreHorizontal, Plus, RefreshCw, Search,
  Send, Settings2, Shield, ShieldAlert, ShieldCheck, Sparkles, WandSparkles, X,
} from "lucide-react";
import { api } from "@/lib/api";

type View = "chat" | "overview" | "knowledge" | "evaluation" | "integrations" | "profile";
type User = { id: string; name: string; email: string; role: "admin" | "user"; createdAt: string };
type Conversation = { id: string; title: string; createdAt: string; updatedAt: string };
type Source = { id: number; title: string; filename: string; topic?: string; page: number; score?: number; excerpt: string };
type Message = { id: string; role: "user" | "assistant"; content: string; sources?: Source[]; createdAt?: string };
type Metrics = { users: number; conversations: number; messages: number; documents: number; ingestionRuns: number; evaluations: number; indexedDocuments: number; indexedChunks: number };
type AdminDocument = { id: string; filename: string; title: string; category: string; status: string; page_count: number; chunk_count: number; indexed_at: string | null; created_at: string };
type IngestionRun = { id: string; status: string; page_count: number; chunk_count: number; started_at: string; finished_at: string | null; error_message?: string | null; filenames?: string[] };
type Trace = { id: string; name: string; runType: string; status: string; latencyMs: number | null; startTime: string | null };
type SavedEvaluation = { id: string; metrics: Record<string, number>; questions: string[]; rows: Record<string, unknown>[]; createdAt: string };

const promptSuggestions = [
  { icon: ShieldAlert, title: "A card payment looks unfamiliar", question: "I see a card transaction I do not recognize. What should I do first?" },
  { icon: Banknote, title: "My loan EMI did not go through", question: "My personal loan EMI was not debited, but my bank account had enough funds. What should I check?" },
  { icon: FileText, title: "I need to close my home loan", question: "What should I check before making a home-loan foreclosure payment?" },
];

const viewTitles: Record<View, { title: string; subtitle: string }> = {
  chat: { title: "Support assistant", subtitle: "A clear next step for your banking questions." },
  overview: { title: "Workspace overview", subtitle: "Your support operation at a glance." },
  knowledge: { title: "Knowledge library", subtitle: "Manage the references behind every answer." },
  evaluation: { title: "Answer quality", subtitle: "Evaluate grounded answers with RAGAS." },
  integrations: { title: "Integrations", subtitle: "Model monitoring and experiment tracking." },
  profile: { title: "Account profile", subtitle: "Your secure Finwell workspace identity." },
};

function initials(name: string) { return name.split(/\s+/).map((part) => part[0]).slice(0, 2).join("").toUpperCase() || "F"; }
function dateLabel(value?: string) { if (!value) return "Recently"; return new Date(value).toLocaleDateString("en-IN", { day: "numeric", month: "short" }); }
function relativeTime(value?: string) { if (!value) return "—"; const mins = Math.floor((Date.now() - new Date(value).getTime()) / 60000); return mins < 1 ? "Just now" : mins < 60 ? `${mins}m ago` : mins < 1440 ? `${Math.floor(mins / 60)}h ago` : dateLabel(value); }

export default function Dashboard() {
  const [user, setUser] = useState<User | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [view, setView] = useState<View>("chat");
  const [input, setInput] = useState("");
  const [strategy, setStrategy] = useState("standard");
  const [strategyMenu, setStrategyMenu] = useState(false);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [documents, setDocuments] = useState<AdminDocument[]>([]);
  const [runs, setRuns] = useState<IngestionRun[]>([]);
  const [uploadFiles, setUploadFiles] = useState<FileList | null>(null);
  const [uploading, setUploading] = useState(false);
  const [reindexing, setReindexing] = useState(false);
  const [evalInput, setEvalInput] = useState("What should I do after an unauthorized card transaction?\nWhat should I ask for before closing a personal loan?");
  const [evaluation, setEvaluation] = useState<{ metrics: Record<string, number>; rows: Record<string, unknown>[] } | null>(null);
  const [evaluationHistory, setEvaluationHistory] = useState<SavedEvaluation[]>([]);
  const [evaluating, setEvaluating] = useState(false);
  const [mlflowConnected, setMlflowConnected] = useState<boolean | null>(null);
  const [langsmithConnected, setLangsmithConnected] = useState<boolean | null>(null);
  const [traces, setTraces] = useState<Trace[]>([]);
  const [integrating, setIntegrating] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const userLabel = user?.name || "Your workspace";
  const isAdmin = user?.role === "admin";

  const loadConversations = useCallback(async () => {
    const result = await api<{ conversations: Conversation[] }>("/api/conversations");
    setConversations(result.conversations);
    return result.conversations;
  }, []);

  const loadAdmin = useCallback(async () => {
    if (!isAdmin) return;
    const [overview, docs, history, savedEvaluations] = await Promise.all([
      api<{ metrics: Metrics; recentRuns: IngestionRun[] }>("/api/admin/overview"),
      api<{ documents: AdminDocument[] }>("/api/admin/documents"),
      api<{ runs: IngestionRun[] }>("/api/admin/ingestion-runs"),
      api<{ evaluations: SavedEvaluation[] }>("/api/admin/evaluations"),
    ]);
    setMetrics(overview.metrics);
    setDocuments(docs.documents);
    setRuns(history.runs);
    setEvaluationHistory(savedEvaluations.evaluations);
    if (savedEvaluations.evaluations.length) setEvaluation((current) => current || savedEvaluations.evaluations[0]);
  }, [isAdmin]);

  useEffect(() => {
    api<{ user: User }>("/api/auth/me").then(async (result) => {
      setUser(result.user);
      const list = await loadConversations();
      if (result.user.role === "admin") {
        const qview = new URLSearchParams(window.location.search).get("view");
        setView(["overview", "knowledge", "evaluation", "integrations", "profile"].includes(qview || "") ? qview as View : "chat");
      } else {
        setView("chat");
      }
      if (list.length) {
        setActiveId(list[0].id);
        const response = await api<{ messages: Message[] }>(`/api/conversations/${list[0].id}`);
        setMessages(response.messages);
      }
    }).catch(() => window.location.replace("/login")).finally(() => setLoading(false));
  }, [loadConversations]);

  useEffect(() => { if (view !== "chat" && isAdmin) loadAdmin().catch((issue) => setError(issue.message)); }, [view, isAdmin, loadAdmin]);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [messages, sending]);

  const currentConversation = useMemo(() => conversations.find((item) => item.id === activeId), [conversations, activeId]);

  async function selectConversation(item: Conversation) {
    setActiveId(item.id); setView("chat"); setError(""); setSidebarOpen(false);
    try { const response = await api<{ messages: Message[] }>(`/api/conversations/${item.id}`); setMessages(response.messages); }
    catch (issue) { setError(issue instanceof Error ? issue.message : "Unable to load conversation."); }
  }

  async function createConversation() {
    const result = await api<{ conversation: Conversation }>("/api/conversations", { method: "POST", body: JSON.stringify({ title: "New conversation" }) });
    setConversations((current) => [result.conversation, ...current]);
    setActiveId(result.conversation.id); setMessages([]); setView("chat"); setError(""); setNotice(""); setSidebarOpen(false);
    return result.conversation.id;
  }

  async function sendMessage(event?: FormEvent<HTMLFormElement>, suggested?: string) {
    event?.preventDefault();
    const content = (suggested || input).trim();
    if (!content || sending) return;
    setInput(""); setError(""); setSending(true); setView("chat");
    let optimistic: Message | null = null;
    try {
      const conversationId = activeId || await createConversation();
      optimistic = { id: `local-${Date.now()}`, role: "user", content };
      setMessages((current) => [...current, optimistic!]);
      const result = await api<{ message: Message }>(`/api/conversations/${conversationId}/messages`, { method: "POST", body: JSON.stringify({ content, strategy }) });
      setMessages((current) => [...current.filter((message) => message.id !== optimistic?.id), result.message]);
      await loadConversations();
    } catch (issue) {
      if (optimistic) setMessages((current) => current.filter((message) => message.id !== optimistic?.id));
      setInput(content); setError(issue instanceof Error ? issue.message : "Message could not be sent.");
    } finally { setSending(false); }
  }

  function handleComposerKey(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void sendMessage(); }
  }

  async function logout() {
    try { await api("/api/auth/logout", { method: "POST", body: JSON.stringify({}) }); } catch { /* Expired sessions are still cleared by navigation. */ }
    window.location.assign("/login");
  }

  function changeView(next: View) {
    setView(next); setNotice(""); setError(""); setSidebarOpen(false);
    window.history.replaceState(null, "", next === "chat" ? "/" : `/?view=${next}`);
  }

  async function uploadKnowledge(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!uploadFiles?.length) { setError("Choose at least one PDF to upload."); return; }
    const form = new FormData();
    Array.from(uploadFiles).forEach((file) => form.append("files", file));
    setUploading(true); setError(""); setNotice("");
    try {
      const result = await api<{ documents: { title: string }[]; pages: number; chunks: number }>("/api/admin/knowledge/ingest", { method: "POST", body: form });
      setNotice(`Indexed ${result.documents.length} document${result.documents.length === 1 ? "" : "s"}, ${result.pages} pages, and ${result.chunks} chunks.`);
      setUploadFiles(null); await loadAdmin();
    } catch (issue) { setError(issue instanceof Error ? issue.message : "Upload failed. Please try again."); }
    finally { setUploading(false); }
  }

  async function reindexCorpus() {
    if (!window.confirm("Reprocess all 50 bundled PDF references and update the search index?")) return;
    setReindexing(true); setError(""); setNotice("");
    try {
      const result = await api<{ documents: number; pages: number; chunks: number }>("/api/admin/knowledge/reindex", { method: "POST", body: JSON.stringify({}) });
      setNotice(`Reindexed ${result.documents} PDFs · ${result.pages} pages · ${result.chunks} chunks.`); await loadAdmin();
    } catch (issue) { setError(issue instanceof Error ? issue.message : "Reindexing failed."); }
    finally { setReindexing(false); }
  }

  async function runEvaluation() {
    const questions = evalInput.split("\n").map((line) => line.trim()).filter(Boolean);
    if (!questions.length) { setError("Add at least one evaluation question."); return; }
    setEvaluating(true); setError(""); setEvaluation(null);
    try {
      const result = await api<{ metrics: Record<string, number>; rows: Record<string, unknown>[] }>("/api/admin/evaluations/ragas", { method: "POST", body: JSON.stringify({ questions }) });
      setEvaluation(result);
      await loadAdmin();
    } catch (issue) { setError(issue instanceof Error ? issue.message : "The evaluation could not run."); }
    finally { setEvaluating(false); }
  }

  async function loadIntegrations() {
    setIntegrating(true); setError("");
    try {
      const [mlflow, langsmith] = await Promise.all([
        api<{ connected: boolean }>("/api/admin/mlflow/status"),
        api<{ connected: boolean; traces: Trace[] }>("/api/admin/langsmith/traces"),
      ]);
      setMlflowConnected(mlflow.connected); setLangsmithConnected(langsmith.connected); setTraces(langsmith.traces || []);
    } catch (issue) { setError(issue instanceof Error ? issue.message : "Could not load integration status."); }
    finally { setIntegrating(false); }
  }

  useEffect(() => { if (view === "integrations" && isAdmin) void loadIntegrations(); }, [view, isAdmin]);

  async function logMlflow() {
    if (!evaluation?.metrics) { setError("Run a RAGAS evaluation before logging its metrics."); return; }
    try {
      const result = await api<{ runId: string }>("/api/admin/mlflow/runs", { method: "POST", body: JSON.stringify({ metrics: evaluation.metrics }) });
      setNotice(`Logged evaluation to MLflow · run ${result.runId.slice(0, 10)}.`);
    } catch (issue) { setError(issue instanceof Error ? issue.message : "MLflow logging failed."); }
  }

  if (loading) return <div className="app-loading"><div className="loading-logo"><Sparkles size={18} /></div><span>Opening your workspace</span></div>;

  const navItem = (target: View, icon: ReactNode, label: string, badge?: string) => (
    <button key={target} className={`nav-item ${view === target ? "active" : ""}`} onClick={() => changeView(target)}>{icon}<span>{label}</span>{badge && <span className="nav-badge">{badge}</span>}</button>
  );

  return (
    <div className={`app-shell ${sidebarOpen ? "sidebar-open" : ""}`}>
      <button className="mobile-scrim" onClick={() => setSidebarOpen(false)} aria-label="Close navigation" />
      <aside className="sidebar">
        <div className="sidebar-brand"><a className="brand" href="/" onClick={(event) => { event.preventDefault(); changeView("chat"); }}><span className="brand-mark"><Sparkles size={16} /></span><span>finwell<span className="brand-dot">.</span></span></a><button className="icon-button sidebar-close" onClick={() => setSidebarOpen(false)} aria-label="Close navigation"><X size={18} /></button></div>
        <div className="workspace-switch"><span className="workspace-avatar"><Shield size={15} /></span><span className="workspace-text"><strong>Finwell Support</strong><small>{isAdmin ? "Administration" : "Personal workspace"}</small></span><ChevronDown size={15} /></div>
        <button className="new-chat-button" onClick={() => void createConversation()}><Plus size={16} />New conversation<span>⌘ K</span></button>
        <div className="sidebar-group"><div className="sidebar-label">WORKSPACE</div>
          {navItem("chat", <MessageCircle size={17} />, "Conversations")}
          {isAdmin && <>
            {navItem("overview", <LayoutDashboard size={17} />, "Overview")}
            {navItem("knowledge", <BookOpen size={17} />, "Knowledge library", metrics?.documents ? String(metrics.indexedDocuments) : undefined)}
            {navItem("evaluation", <Gauge size={17} />, "Answer quality")}
            {navItem("integrations", <Activity size={17} />, "Integrations")}
          </>}
        </div>
        <div className="sidebar-history-head"><span className="sidebar-label">RECENT CONVERSATIONS</span><button className="icon-button small-icon" onClick={() => void loadConversations()} title="Refresh conversations"><RefreshCw size={14} /></button></div>
        <div className="conversation-list">
          {conversations.length === 0 && <div className="history-empty">Your conversations<br />will show up here.</div>}
          {conversations.slice(0, 16).map((item) => <button key={item.id} className={`conversation-item ${activeId === item.id && view === "chat" ? "selected" : ""}`} onClick={() => void selectConversation(item)}><MessageCircle size={14} /><span>{item.title || "New conversation"}</span><small>{dateLabel(item.updatedAt)}</small></button>)}
        </div>
        <div className="sidebar-bottom">
          <div className="sidebar-help"><span className="help-icon"><CircleHelp size={15} /></span><div><strong>Need urgent help?</strong><span>Contact your bank directly</span></div><ArrowUpRight size={14} /></div>
          <div className="sidebar-user"><div className="avatar avatar-small">{initials(userLabel)}</div><div className="sidebar-user-meta"><strong>{userLabel}</strong><span>{isAdmin ? "Administrator" : user?.email}</span></div><button className="icon-button" onClick={() => changeView("profile")} title="Profile"><Settings2 size={17} /></button><button className="icon-button" onClick={() => void logout()} title="Sign out"><LogOut size={17} /></button></div>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar"><div className="topbar-left"><button className="icon-button mobile-menu" onClick={() => setSidebarOpen(true)} aria-label="Open navigation"><MoreHorizontal size={20} /></button><div className="breadcrumbs"><span>Finwell Support</span><span className="crumb-slash">/</span><strong>{viewTitles[view].title}</strong></div></div><div className="topbar-right"><div className="secure-pill"><span className="pulse-dot" />Secure workspace</div><button className="help-button" title="Support"><Headphones size={17} /></button><button className="avatar" onClick={() => changeView("profile")} title="Profile">{initials(userLabel)}</button></div></header>

        {(error || notice) && <div className={`toast ${error ? "toast-error" : "toast-success"}`} role="status"><span>{error || notice}</span><button className="icon-button" onClick={() => { setError(""); setNotice(""); }}><X size={16} /></button></div>}

        {view === "chat" && <section className="chat-page">
          <div className="page-heading"><div><div className="eyebrow">FINWELL ASSISTANT</div><h1>{currentConversation?.title || "How can we help?"}</h1><p>Clear, source-backed guidance for cards and loans.</p></div><div className="chat-controls"><div className="source-status"><span className="status-dot" />{metrics?.indexedChunks ? `${metrics.indexedChunks.toLocaleString()} sources indexed` : "Reference-backed answers"}</div><div className="strategy-wrap"><button className="strategy-button" onClick={() => setStrategyMenu(!strategyMenu)}><WandSparkles size={15} />{strategy === "standard" ? "Standard" : strategy === "cot" ? "Stepwise review" : "Multi-path review"}<ChevronDown size={14} /></button>{strategyMenu && <div className="strategy-menu">{[["standard", "Standard", "Direct sourced answer"], ["cot", "Stepwise review", "Careful internal evidence check"], ["tot", "Multi-path review", "Compare answer paths" ]].map(([id, label, hint]) => <button key={id} onClick={() => { setStrategy(id); setStrategyMenu(false); }}><span><strong>{label}</strong><small>{hint}</small></span>{strategy === id && <Check size={15} />}</button>)}</div>}</div></div></div>
          <div className={`messages-area ${messages.length ? "has-messages" : ""}`}>
            {messages.length === 0 ? <div className="welcome-content"><div className="welcome-icon"><Sparkles size={22} /></div><div className="welcome-kicker">A LITTLE CLARITY GOES A LONG WAY</div><h2>Let’s work through it<br />together.</h2><p>Ask about a payment, a card issue, or a loan. I’ll point you to practical next steps and the references that support them.</p><div className="suggestion-grid">{promptSuggestions.map(({ icon: Icon, title, question }) => <button className="suggestion-card" key={title} onClick={() => void sendMessage(undefined, question)}><span className="suggestion-icon"><Icon size={17} /></span><span>{title}</span><ArrowUpRight size={15} className="suggestion-arrow" /></button>)}</div><div className="privacy-reminder"><Shield size={14} /><span>Please don’t include card numbers, CVV, PIN, OTP, or banking passwords.</span></div></div>
              : <div className="message-thread">{messages.map((message) => <article className={`message-row ${message.role}`} key={message.id}><div className="message-avatar">{message.role === "assistant" ? <Sparkles size={15} /> : initials(userLabel)}</div><div className="message-body"><div className="message-meta"><strong>{message.role === "assistant" ? "Finwell assistant" : "You"}</strong><span>{message.createdAt ? relativeTime(message.createdAt) : "Just now"}</span></div><div className="message-content">{message.content}</div>{message.sources?.length ? <div className="source-list"><div className="source-list-heading"><BookOpen size={14} />Sources used</div>{message.sources.map((source) => <SourceReference source={source} key={`${message.id}-${source.id}`} />)}</div> : null}</div></article>)}{sending && <article className="message-row assistant"><div className="message-avatar"><Sparkles size={15} /></div><div className="message-body"><div className="message-meta"><strong>Finwell assistant</strong><span>Finding relevant guidance</span></div><div className="thinking-card"><span className="thinking-dots"><i /><i /><i /></span><span>Reviewing your question and references</span></div></div></article>}<div ref={bottomRef} /></div>}
          </div>
          <div className="composer-wrap"><form className="composer" onSubmit={(event) => void sendMessage(event)}><textarea value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={handleComposerKey} placeholder="Ask a question about your card or loan…" rows={1} maxLength={4000} aria-label="Ask Finwell a question" /><div className="composer-footer"><div className="composer-hint"><span className="composer-tip"><Sparkles size={13} /> Answers include supporting references</span><span className="char-count">{input.length}/4000</span></div><button type="submit" disabled={!input.trim() || sending} className="send-button">{sending ? <span className="spinner" /> : <><span>Send</span><Send size={15} /></>}</button></div></form><div className="composer-disclaimer">Finwell provides general guidance. Your bank’s terms and decisions apply.</div></div>
        </section>}

        {view === "overview" && isAdmin && <section className="admin-page"><div className="admin-heading"><div><div className="eyebrow">ADMINISTRATION</div><h1>Workspace overview</h1><p>Monitor the assistant, reference documents, and processing activity.</p></div><button className="secondary-button" onClick={() => void loadAdmin()}><RefreshCw size={15} />Refresh data</button></div><div className="metric-grid">{[["Indexed documents", metrics?.indexedDocuments ?? "—", "Reference PDFs available", <FileText size={18} />], ["Indexed chunks", metrics?.indexedChunks?.toLocaleString() ?? "—", "Searchable page passages", <Database size={18} />], ["Customer conversations", metrics?.conversations ?? "—", "Saved support threads", <MessageCircle size={18} />], ["RAGAS evaluations", metrics?.evaluations ?? "—", "Saved quality checks", <Shield size={18} />]].map(([label, value, hint, icon]) => <div className="metric-card" key={String(label)}><div className="metric-top"><span>{label}</span><span className="metric-icon">{icon}</span></div><strong>{value}</strong><small>{hint}</small></div>)}</div><div className="admin-columns"><div className="panel-card"><div className="panel-heading"><div><h2>Recent document activity</h2><p>Latest knowledge-base processing jobs</p></div><button className="text-button" onClick={() => changeView("knowledge")}>View library <ArrowUpRight size={14} /></button></div><RunTable runs={runs.slice(0, 6)} /></div><div className="panel-card system-card"><div className="panel-heading"><div><h2>System status</h2><p>Core assistant components</p></div><span className="live-badge"><span className="status-dot" />Operational</span></div>{[["Web application", "Available"], ["RAG API", "Connected"], ["Vector retrieval", metrics?.indexedChunks ? "Indexed" : "Awaiting index"], ["SQLite records", "Available"]].map(([label, value]) => <div className="status-row" key={label}><span>{label}</span><span className="status-value"><i className="status-dot" />{value}</span></div>)}</div></div><div className="tip-banner"><div className="tip-icon"><Sparkles size={18} /></div><div><strong>Keep answers grounded</strong><p>Use the quality workspace to review retrieval, faithfulness, and answer relevance on a small set of sample questions.</p></div><button className="secondary-button" onClick={() => changeView("evaluation")}>Run an evaluation <ArrowUpRight size={14} /></button></div></section>}

        {view === "knowledge" && isAdmin && <section className="admin-page"><div className="admin-heading"><div><div className="eyebrow">CONTENT OPERATIONS</div><h1>Knowledge library</h1><p>Process PDFs into searchable, source-cited guidance.</p></div><button className="secondary-button" disabled={reindexing} onClick={() => void reindexCorpus()}>{reindexing ? <span className="spinner dark-spinner" /> : <RefreshCw size={15} />}{reindexing ? "Reindexing 50 PDFs" : "Reindex bundled set"}</button></div><div className="knowledge-flow"><div className="flow-step"><span>01</span><strong>Upload PDF</strong><small>PDF text is extracted securely</small></div><ArrowDown size={17} className="flow-arrow" /><div className="flow-step"><span>02</span><strong>Split & enrich</strong><small>Pages become overlapping chunks</small></div><ArrowDown size={17} className="flow-arrow" /><div className="flow-step"><span>03</span><strong>Embed</strong><small>LangChain creates vector embeddings</small></div><ArrowDown size={17} className="flow-arrow" /><div className="flow-step"><span>04</span><strong>Index & cite</strong><small>Retrieval returns source and page</small></div></div><div className="upload-panel panel-card"><div className="upload-copy"><div className="upload-icon"><FilePlus2 size={19} /></div><div><h2>Add reference documents</h2><p>Upload up to five text-based PDFs per job, 4 MB total. Indexed references are available in answer citations.</p></div></div><form className="upload-form" onSubmit={(event) => void uploadKnowledge(event)}><label className="file-picker"><input type="file" accept="application/pdf,.pdf" multiple onChange={(event) => setUploadFiles(event.target.files)} /><FilePlus2 size={16} /><span>{uploadFiles?.length ? `${uploadFiles.length} PDF${uploadFiles.length === 1 ? "" : "s"} selected` : "Choose PDF files"}</span></label><button className="primary-button" disabled={uploading || !uploadFiles?.length}>{uploading ? <><span className="spinner" />Processing</> : <>Process documents <ArrowUpRight size={15} /></>}</button></form></div><div className="panel-card table-panel"><div className="panel-heading"><div><h2>Processed documents</h2><p>{documents.length} document records · individual sources cited by page</p></div><div className="table-search"><Search size={14} /><span>Search-ready</span></div></div><DocumentTable documents={documents} /></div><div className="panel-card table-panel"><div className="panel-heading"><div><h2>Processing history</h2><p>Document pages, chunks, and job status</p></div><span className="count-label">{runs.length} runs</span></div><RunTable runs={runs} /></div></section>}

        {view === "evaluation" && isAdmin && <section className="admin-page"><div className="admin-heading"><div><div className="eyebrow">MODEL QUALITY</div><h1>Answer quality</h1><p>Run groundedness and answer-relevance checks across sample questions.</p></div><span className="powered-badge"><Sparkles size={14} />RAGAS</span></div><div className="evaluation-layout"><div className="panel-card evaluation-input"><div className="panel-heading"><div><h2>Evaluation dataset</h2><p>One question per line · up to 4 at a time</p></div><span className="count-label">{evalInput.split("\n").filter((line) => line.trim()).length} questions</span></div><textarea className="eval-textarea" value={evalInput} onChange={(event) => setEvalInput(event.target.value)} placeholder="Enter a customer support question on each line…" rows={7} /><div className="eval-actions"><span><ShieldCheckIcon />Uses references from your active index</span><button className="primary-button" onClick={() => void runEvaluation()} disabled={evaluating}>{evaluating ? <><span className="spinner" />Evaluating</> : <>Run RAGAS <ArrowUpRight size={15} /></>}</button></div></div><div className="evaluation-aside"><div className="metric-explainer"><span className="metric-explainer-icon"><BadgeCheck size={18} /></span><strong>Faithfulness</strong><p>Checks whether the answer is supported by retrieved passages.</p></div><div className="metric-explainer"><span className="metric-explainer-icon lilac"><Sparkles size={18} /></span><strong>Answer relevance</strong><p>Checks whether the response addresses the customer’s question.</p></div><div className="privacy-card"><Shield size={16} /><span>Evaluations run with the configured language model and embedding provider.</span></div></div></div>{evaluation && <div className="panel-card results-panel"><div className="panel-heading"><div><h2>Latest evaluation</h2><p>Scores range from 0 to 1. Higher values indicate a stronger score.</p></div><button className="secondary-button" onClick={() => void logMlflow()}><Activity size={15} />Log to MLflow</button></div><div className="score-grid">{Object.entries(evaluation.metrics).map(([label, value]) => <div className="score-card" key={label}><span>{label.replaceAll("_", " ")}</span><strong>{Number(value).toFixed(3)}</strong><div className="score-track"><i style={{ width: `${Math.max(0, Math.min(1, Number(value))) * 100}%` }} /></div></div>)}</div><div className="eval-results-list">{evaluation.rows.map((row, index) => <div className="eval-result-row" key={index}><span className="result-index">{String(index + 1).padStart(2, "0")}</span><span className="result-question">{String(row.question || "Evaluation item")}</span><span className="result-score">{row.faithfulness !== undefined ? `F ${Number(row.faithfulness).toFixed(2)}` : ""} {row.answer_relevancy !== undefined ? ` · R ${Number(row.answer_relevancy).toFixed(2)}` : ""}</span></div>)}</div></div>}</section>}

        {view === "evaluation" && isAdmin && evaluationHistory.length > 0 && <section className="admin-page evaluation-history-section"><div className="panel-card table-panel"><div className="panel-heading"><div><h2>Saved evaluations</h2><p>Choose a prior run to review its RAGAS scores.</p></div><span className="count-label">{evaluationHistory.length} runs</span></div><EvaluationHistoryTable items={evaluationHistory} onSelect={(item) => { setEvaluation({ metrics: item.metrics, rows: item.rows }); setEvalInput(item.questions.join("\n")); }} /></div></section>}

        {view === "integrations" && isAdmin && <section className="admin-page"><div className="admin-heading"><div><div className="eyebrow">OBSERVABILITY</div><h1>Integrations</h1><p>Review model traces and send evaluation metrics to experiment tracking.</p></div><button className="secondary-button" onClick={() => void loadIntegrations()} disabled={integrating}>{integrating ? <span className="spinner dark-spinner" /> : <RefreshCw size={15} />}Refresh connections</button></div><div className="integration-grid"><div className="integration-card"><div className="integration-top"><div className="integration-logo langsmith-logo"><Activity size={19} /></div><span className={`connection-pill ${langsmithConnected ? "connected" : "not-connected"}`}><i />{langsmithConnected ? "Connected" : "Not configured"}</span></div><h2>LangSmith</h2><p>Trace LangChain retrieval and answer generation to inspect latency and execution status.</p><div className="integration-bottom"><span>Project: <strong>finwell-support</strong></span><button className="text-button" onClick={() => void loadIntegrations()}>View traces <ArrowUpRight size={14} /></button></div></div><div className="integration-card"><div className="integration-top"><div className="integration-logo mlflow-logo"><Gauge size={19} /></div><span className={`connection-pill ${mlflowConnected ? "connected" : "not-connected"}`}><i />{mlflowConnected ? "Connected" : "Not configured"}</span></div><h2>MLflow</h2><p>Track quality metrics across RAG evaluations and compare model or prompt revisions.</p><div className="integration-bottom"><span>Experiment: <strong>finwell-rag</strong></span><button className="text-button" onClick={() => evaluation ? void logMlflow() : changeView("evaluation")}>{evaluation ? "Log latest run" : "Run an evaluation"} <ArrowUpRight size={14} /></button></div></div></div><div className="panel-card table-panel"><div className="panel-heading"><div><h2>Recent LangSmith traces</h2><p>Root runs from the configured project. Customer messages are not displayed here.</p></div><span className="count-label">{traces.length} traces</span></div>{traces.length ? <div className="trace-table"><div className="table-head trace-grid"><span>Run</span><span>Type</span><span>Status</span><span>Latency</span><span>Started</span></div>{traces.map((trace) => <div className="table-row trace-grid" key={trace.id}><span className="trace-name">{trace.name}</span><span>{trace.runType || "chain"}</span><span><span className={`mini-status ${trace.status === "completed" ? "" : "status-fail"}`} />{trace.status}</span><span>{trace.latencyMs ? `${trace.latencyMs} ms` : "—"}</span><span>{relativeTime(trace.startTime || undefined)}</span></div>)}</div> : <div className="empty-table"><Activity size={20} /><span>Trace runs will appear here once LangSmith is configured.</span></div>}</div><div className="integration-note"><Shield size={15} /><span>Configure API keys and tracking endpoints in the deployment environment. Credentials are never stored in the browser.</span></div></section>}

        {view === "profile" && <section className="admin-page profile-page"><div className="admin-heading"><div><div className="eyebrow">YOUR ACCOUNT</div><h1>Profile & security</h1><p>Manage your Finwell sign-in identity.</p></div></div><div className="profile-card panel-card"><div className="profile-cover" /><div className="profile-main"><div className="avatar profile-avatar">{initials(userLabel)}</div><div className="profile-identity"><h2>{user?.name}</h2><p>{user?.email}</p><span className="role-chip"><BadgeCheck size={13} />{isAdmin ? "Administrator" : "Customer"}</span></div><button className="secondary-button" onClick={() => void logout()}><LogOut size={15} />Sign out</button></div><div className="profile-details"><div><span>Account email</span><strong>{user?.email}</strong></div><div><span>Workspace role</span><strong>{isAdmin ? "Administrator" : "Customer"}</strong></div><div><span>Member since</span><strong>{dateLabel(user?.createdAt)}</strong></div><div><span>Session protection</span><strong className="profile-secure"><ShieldCheck size={14} />Secure cookie</strong></div></div></div><div className="privacy-card profile-privacy"><Shield size={17} /><div><strong>Protect your banking details</strong><span>Never enter your complete card number, CVV, PIN, OTP, password, or full identity number into a support conversation.</span></div></div></section>}
      </main>
    </div>
  );
}

function ShieldCheckIcon() { return <ShieldCheckMini />; }
function ShieldCheckMini() { return <Shield size={14} />; }

function RunTable({ runs }: { runs: IngestionRun[] }) {
  if (!runs.length) return <div className="empty-table"><FileClock size={19} /><span>No processing jobs recorded yet.</span></div>;
  return <div className="simple-table"><div className="table-head run-grid"><span>Job</span><span>Status</span><span>Pages</span><span>Chunks</span><span>Started</span></div>{runs.map((run) => <div className="table-row run-grid" key={run.id}><span className="run-id">{run.id.slice(0, 8)}</span><span><span className={`run-status ${run.status.includes("completed") ? "run-done" : run.status === "processing" ? "run-processing" : "run-error"}`}><i />{run.status.replaceAll("_", " ")}</span></span><span>{run.page_count || 0}</span><span>{run.chunk_count || 0}</span><span>{relativeTime(run.started_at)}</span></div>)}</div>;
}

function DocumentTable({ documents }: { documents: AdminDocument[] }) {
  if (!documents.length) return <div className="empty-table"><BookOpen size={20} /><span>No document records yet. Process the bundled set or upload a PDF.</span></div>;
  return <div className="simple-table"><div className="table-head doc-grid"><span>Document</span><span>Category</span><span>Status</span><span>Pages</span><span>Chunks</span><span>Updated</span></div>{documents.map((doc) => <div className="table-row doc-grid" key={doc.id}><DocumentFileLink doc={doc} /><span>{doc.category}</span><span><span className={`run-status ${doc.status === "indexed" ? "run-done" : "run-error"}`}><i />{doc.status}</span></span><span>{doc.page_count}</span><span>{doc.chunk_count}</span><span>{relativeTime(doc.indexed_at || doc.created_at)}</span></div>)}</div>;
}

function DocumentFileLink({ doc }: { doc: AdminDocument }) {
  const content = <><span className="document-type"><FileText size={15} /></span><span><strong>{doc.title}</strong><small>{doc.filename}</small></span></>;
  return doc.filename.startsWith("FW-")
    ? <a className="document-name" href={`/knowledge_base/pdfs/${encodeURIComponent(doc.filename)}`} target="_blank" rel="noreferrer">{content}</a>
    : <span className="document-name">{content}</span>;
}

function EvaluationHistoryTable({ items, onSelect }: { items: SavedEvaluation[]; onSelect: (item: SavedEvaluation) => void }) {
  return <div className="simple-table"><div className="table-head evaluation-grid"><span>Evaluation run</span><span>Questions</span><span>Faithfulness</span><span>Answer relevance</span><span>Created</span><span /></div>{items.map((item) => <div className="table-row evaluation-grid" key={item.id}><span className="run-id">{item.id.slice(0, 8)}</span><span>{item.questions.length}</span><span>{item.metrics.faithfulness !== undefined ? Number(item.metrics.faithfulness).toFixed(3) : "—"}</span><span>{(item.metrics.answer_relevancy ?? item.metrics.response_relevancy) !== undefined ? Number(item.metrics.answer_relevancy ?? item.metrics.response_relevancy).toFixed(3) : "—"}</span><span>{relativeTime(item.createdAt)}</span><button className="text-button" onClick={() => onSelect(item)}>Review</button></div>)}</div>;
}

function SourceReference({ source }: { source: Source }) {
  const content = <><span className="source-number">{source.id}</span><span className="source-info"><strong>{source.title}</strong><small>{source.topic || "Reference"} · page {source.page}</small></span>{source.filename.startsWith("FW-") && <ArrowUpRight size={14} />}</>;
  return source.filename.startsWith("FW-")
    ? <a className="source-card" href={`/knowledge_base/pdfs/${encodeURIComponent(source.filename)}`} target="_blank" rel="noreferrer">{content}</a>
    : <div className="source-card" title="Uploaded reference passage">{content}</div>;
}



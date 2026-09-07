import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { AskBar, DEFAULT_CONTROLS } from "./components/AskBar";
import {
  CanvasTab, ChatTab, CitationsTab, DataTab, FilesTab, ImagesTab, MapTab, NotesTab,
  ProvidersTab, SourcesTab, describeError,
} from "./components/tabs";
import { AnswerView } from "./components/AnswerView";
import { Empty, Spinner } from "./components/common";
import type {
  Answer, Capabilities, Controls, Message, Note, Project, ProvidersReport, Source,
} from "./types";

type TabId =
  | "ask" | "sources" | "chat" | "files" | "images" | "data"
  | "canvas" | "notes" | "citations" | "map" | "providers";

const TABS: { id: TabId; label: string }[] = [
  { id: "ask", label: "Ask" },
  { id: "sources", label: "Sources" },
  { id: "chat", label: "Chat" },
  { id: "files", label: "Files" },
  { id: "images", label: "Images" },
  { id: "data", label: "Data" },
  { id: "canvas", label: "Canvas" },
  { id: "notes", label: "Notes" },
  { id: "citations", label: "Citations" },
  { id: "map", label: "Map" },
  { id: "providers", label: "Providers" },
];

export default function App() {
  const [theme, setTheme] = useState<"light" | "dark">(
    () => (localStorage.getItem("theme") as "light" | "dark") || "light",
  );
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [notes, setNotes] = useState<Note[]>([]);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [providers, setProviders] = useState<ProvidersReport | null>(null);
  const [tab, setTab] = useState<TabId>("ask");
  const [busy, setBusy] = useState(false);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [toast, setToast] = useState<{ text: string; error: boolean } | null>(null);
  const [seed, setSeed] = useState("");

  const [mode, setMode] = useState("quick");
  const [controls, setControls] = useState<Controls>(DEFAULT_CONTROLS);
  const [depth, setDepth] = useState("standard");
  const [level, setLevel] = useState("researcher");
  const [style, setStyle] = useState("apa");

  const project = useMemo(
    () => projects.find((p) => p.id === projectId) || null,
    [projects, projectId],
  );

  const hasReasoningModel = Boolean(
    providers?.capabilities?.llm?.active &&
      providers.capabilities.llm.active !== "extractive",
  );

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("theme", theme);
  }, [theme]);

  const notify = useCallback((text: string, error = false) => {
    setToast({ text, error });
    setTimeout(() => setToast(null), error ? 9000 : 4000);
  }, []);

  const fail = useCallback(
    (error: unknown) => notify(describeError(error), true),
    [notify],
  );

  /* ---------------------------------------------------------------- boot */
  // StrictMode mounts effects twice in development; without this guard the
  // bootstrap would create two starter projects.
  const booted = useRef(false);
  useEffect(() => {
    if (booted.current) return;
    booted.current = true;
    api.capabilities().then(setCapabilities).catch(fail);
    api.providers().then(setProviders).catch(fail);
    api
      .listProjects()
      .then(async (list) => {
        if (list.length) {
          setProjects(list);
          setProjectId(list[0].id);
          return;
        }
        const created = await api.createProject({
          name: "My first research project",
          question: "",
        });
        setProjects([created]);
        setProjectId(created.id);
      })
      .catch(fail);
  }, [fail]);

  const refreshProject = useCallback(async () => {
    if (!projectId) return;
    try {
      const [sourceList, messageList, noteList, refreshed] = await Promise.all([
        api.listSources(projectId, style),
        api.messages(projectId),
        api.notes(projectId),
        api.getProject(projectId),
      ]);
      setSources(sourceList.items);
      setMessages(messageList.items);
      setNotes(noteList.items);
      setProjects((all) => all.map((p) => (p.id === refreshed.id ? refreshed : p)));
    } catch (error) {
      fail(error);
    }
  }, [projectId, style, fail]);

  useEffect(() => {
    refreshProject();
  }, [refreshProject]);

  /* ---------------------------------------------------------------- ask */
  const ask = async (question: string, from: "ask" | "chat" = "ask") => {
    if (!projectId) return;
    setBusy(true);
    setAnswer(null);
    // Asking from the Chat composer should leave you in Chat, where the new
    // turn appears in the thread you were already reading.
    if (from === "ask") setTab("ask");
    try {
      const result = await api.research({
        question,
        project_id: projectId,
        mode,
        controls,
        depth,
        level,
        citation_style: style,
      });
      setAnswer(result);
      await refreshProject();
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  };

  const exportAnswer = async (messageId: string | null, format: string) => {
    try {
      await api.exportAnswer(
        messageId
          ? { message_id: messageId, format, style }
          : { answer, format, style },
      );
    } catch (error) {
      fail(error);
    }
  };

  const saveFinding = async (claim: any) => {
    if (!projectId) return;
    try {
      await fetch(`/api/projects/${projectId}/findings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(claim),
      });
      notify("Saved to project findings.");
    } catch (error) {
      fail(error);
    }
  };

  const counts: Partial<Record<TabId, number>> = {
    sources: sources.length,
    chat: messages.filter((m) => m.role === "assistant").length,
    images: sources.filter((s) => s.kind === "image").length,
    data: sources.filter((s) => s.kind === "dataset").length,
    notes: notes.length,
    citations: sources.length,
  };

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <span className="dot" />
          <div>
            Lumen
            <small>Research workspace</small>
          </div>
        </div>
        <div className="sidebar-scroll">
          <div className="side-label">
            Projects
            <button
              className="btn ghost small"
              title="New project"
              onClick={async () => {
                const name = prompt("Project name");
                if (!name) return;
                try {
                  const created = await api.createProject({ name });
                  setProjects((all) => [created, ...all]);
                  setProjectId(created.id);
                  setAnswer(null);
                } catch (error) {
                  fail(error);
                }
              }}
            >
              +
            </button>
          </div>
          {projects.map((p) => (
            <button
              key={p.id}
              className={`project-item ${p.id === projectId ? "active" : ""}`}
              onClick={() => {
                setProjectId(p.id);
                setAnswer(null);
              }}
            >
              {p.name}
              <span className="meta">
                {p.source_count} sources · {p.message_count} turns
              </span>
            </button>
          ))}

          {providers && providers.degraded.length > 0 && (
            <>
              <div className="side-label">Unavailable</div>
              <div style={{ padding: "0 8px" }}>
                {providers.degraded.map((capability) => (
                  <div key={capability} className="badge critical" style={{ marginBottom: 4 }}>
                    {capability.replace(/_/g, " ")}
                  </div>
                ))}
                <button
                  className="btn ghost small"
                  style={{ marginTop: 6 }}
                  onClick={() => setTab("providers")}
                >
                  Why?
                </button>
              </div>
            </>
          )}
        </div>
      </aside>

      <main className="main">
        <div className="topbar">
          <div>
            <h1>{project?.name || "Loading…"}</h1>
            {project?.question && <div className="sub">{project.question}</div>}
          </div>
          <span className="spacer" />
          <button
            className="btn ghost small"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            title="Toggle theme"
          >
            {theme === "dark" ? "☀" : "☾"}
          </button>
        </div>

        <nav className="tabs">
          {TABS.map((entry) => (
            <button
              key={entry.id}
              className={`tab ${tab === entry.id ? "active" : ""}`}
              onClick={() => setTab(entry.id)}
            >
              {entry.label}
              {counts[entry.id] ? <span className="count">{counts[entry.id]}</span> : null}
            </button>
          ))}
        </nav>

        <div className="content">
          <div className="content-narrow">
            {tab === "ask" && (
              <>
                <AskBar
                  capabilities={capabilities}
                  mode={mode}
                  onModeChange={setMode}
                  controls={controls}
                  onControlsChange={setControls}
                  depth={depth}
                  onDepthChange={setDepth}
                  level={level}
                  onLevelChange={setLevel}
                  onAsk={ask}
                  busy={busy}
                  hasReasoningModel={hasReasoningModel}
                  seed={seed}
                />
                {busy && (
                  <div className="card">
                    <Spinner label="Searching, reading and checking sources…" />
                  </div>
                )}
                {answer && !busy && (
                  <AnswerView
                    answer={answer}
                    onFollowup={(q) => setSeed(q)}
                    onExport={(format) => exportAnswer(null, format)}
                    onSaveFinding={saveFinding}
                  />
                )}
                {!answer && !busy && (
                  <Empty title="What are you investigating?">
                    <p>
                      Every answer here tells you three things: what was found, where it came
                      from, and how certain it is. Statements that no source supports are
                      labelled as the model's own inference rather than dressed up as findings.
                    </p>
                    <div className="pill-row" style={{ justifyContent: "center" }}>
                      {[
                        "Find recent research about CRISPR-based cancer therapy",
                        "What are the conflicting findings in this field?",
                        "Find the original source of this claim",
                      ].map((example) => (
                        <button key={example} className="chip" onClick={() => setSeed(example)}>
                          {example}
                        </button>
                      ))}
                    </div>
                  </Empty>
                )}
              </>
            )}

            {project && tab === "sources" && (
              <SourcesTab
                project={project} sources={sources} reload={refreshProject}
                onFail={fail} style={style}
              />
            )}
            {tab === "chat" && (
              <ChatTab
                messages={messages}
                onFollowup={(q) => { setSeed(q); setTab("ask"); }}
                onExport={(messageId, format) => exportAnswer(messageId, format)}
                onSaveFinding={saveFinding}
                onAsk={(q) => ask(q, "chat")}
                busy={busy}
                mode={mode}
              />
            )}
            {project && tab === "files" && (
              <FilesTab project={project} sources={sources} reload={refreshProject} onFail={fail} />
            )}
            {tab === "images" && (
              <ImagesTab
                sources={sources} onFail={fail} hasVisionModel={hasReasoningModel}
              />
            )}
            {project && tab === "data" && (
              <DataTab
                project={project} sources={sources} capabilities={capabilities} onFail={fail}
              />
            )}
            {project && tab === "canvas" && (
              <CanvasTab project={project} sources={sources} onFail={fail} />
            )}
            {project && tab === "notes" && (
              <NotesTab project={project} notes={notes} reload={refreshProject} onFail={fail} />
            )}
            {project && tab === "citations" && (
              <CitationsTab
                project={project} sources={sources} style={style}
                onStyleChange={setStyle} capabilities={capabilities} onFail={fail}
              />
            )}
            {project && tab === "map" && <MapTab project={project} onFail={fail} />}
            {tab === "providers" && <ProvidersTab report={providers} />}
          </div>
        </div>
      </main>

      {toast && (
        <div className={`toast ${toast.error ? "error" : ""}`}>{toast.text}</div>
      )}
    </div>
  );
}

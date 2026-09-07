import { useEffect, useMemo, useRef, useState } from "react";
import { api, WorkspaceApiError } from "../api";
import type {
  Answer, Capabilities, ChartSpec, Diagram, Graph, Message, Note, Project, Source,
} from "../types";
import { AnswerView, SourceDrawer } from "./AnswerView";
import { Chart } from "./Chart";
import { Empty, Spinner, TierBadge, sourceLine } from "./common";

type Fail = (error: unknown) => void;

/* ------------------------------------------------------------------ Sources */
export function SourcesTab({
  project, sources, reload, onFail, style,
}: {
  project: Project;
  sources: Source[];
  reload: () => void;
  onFail: Fail;
  style: string;
}) {
  const [open, setOpen] = useState<Source | null>(null);
  const [filter, setFilter] = useState("");
  const [tier, setTier] = useState("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [synthesis, setSynthesis] = useState<any>(null);

  const shown = sources.filter((s) => {
    if (tier !== "all" && s.quality?.tier !== tier) return false;
    if (!filter.trim()) return true;
    const needle = filter.toLowerCase();
    return (
      s.title.toLowerCase().includes(needle) ||
      s.authors.some((a) => a.name.toLowerCase().includes(needle)) ||
      (s.container_title || "").toLowerCase().includes(needle)
    );
  });

  const toggle = (id: string) => {
    const next = new Set(selected);
    next.has(id) ? next.delete(id) : next.add(id);
    setSelected(next);
  };

  const compare = async () => {
    setBusy(true);
    setSynthesis(null);
    try {
      setSynthesis(
        await api.synthesise({
          project_id: project.id,
          source_ids: selected.size ? [...selected] : undefined,
          question: project.question || null,
        }),
      );
    } catch (error) {
      onFail(error);
    } finally {
      setBusy(false);
    }
  };

  if (!sources.length) {
    return (
      <Empty title="No sources yet">
        <p>
          Ask a research question, paste a URL or a video link, or upload papers and datasets.
          Everything you collect lands here with its provenance and an appraisal of how far it
          can be trusted.
        </p>
      </Empty>
    );
  }

  return (
    <div>
      <div className="row wrap" style={{ marginBottom: 14, gap: 10 }}>
        <input
          type="search" placeholder="Filter by title, author or venue…"
          value={filter} onChange={(e) => setFilter(e.target.value)}
          style={{ maxWidth: 320 }}
        />
        <select value={tier} onChange={(e) => setTier(e.target.value)} style={{ maxWidth: 220 }}>
          <option value="all">All evidence tiers</option>
          {[...new Set(sources.map((s) => s.quality?.tier).filter(Boolean))].map((t) => (
            <option key={t} value={t as string}>
              {(t as string).replace(/_/g, " ")}
            </option>
          ))}
        </select>
        <span className="spacer" />
        <span className="muted small">
          {selected.size ? `${selected.size} selected` : `${shown.length} of ${sources.length}`}
        </span>
        <button className="btn" disabled={busy || sources.length < 2} onClick={compare}>
          {busy ? <span className="spinner" /> : "Compare papers"}
        </button>
      </div>

      {synthesis && <SynthesisView data={synthesis} onClose={() => setSynthesis(null)} />}

      {shown.map((source) => (
        <div key={source.id} className="source-card">
          <div className="row" style={{ alignItems: "flex-start", gap: 10 }}>
            <input
              type="checkbox" checked={selected.has(source.id)}
              onChange={() => toggle(source.id)} style={{ width: "auto", marginTop: 4 }}
            />
            <div style={{ flex: 1, minWidth: 0 }} onClick={() => setOpen(source)}>
              <div className="title" style={{ cursor: "pointer" }}>{source.title}</div>
              <div className="meta">{sourceLine(source)}</div>
              <div className="pill-row">
                <TierBadge tier={source.quality?.tier} />
                <span className="badge neutral">{source.kind.replace(/_/g, " ")}</span>
                {source.origin && <span className="badge neutral">via {source.origin}</span>}
                {!source.full_text_retrieved && <span className="badge neutral">abstract only</span>}
                {source.passage_count ? (
                  <span className="badge neutral">{source.passage_count} passages</span>
                ) : null}
                {source.retracted && <span className="badge critical">retracted</span>}
              </div>
              {source.citation && (
                <div className="small muted" style={{ marginTop: 7 }}>{source.citation}</div>
              )}
            </div>
            <div className="row" style={{ gap: 4 }}>
              {source.url && (
                <a className="btn ghost small" href={source.url} target="_blank" rel="noreferrer">
                  Open ↗
                </a>
              )}
              <button
                className="btn ghost small danger"
                onClick={async () => {
                  try {
                    await api.deleteSource(project.id, source.id);
                    reload();
                  } catch (error) {
                    onFail(error);
                  }
                }}
              >
                Remove
              </button>
            </div>
          </div>
        </div>
      ))}
      {open && <SourceDrawer source={open} onClose={() => setOpen(null)} />}
      <div className="small muted">Citation style: {style.toUpperCase()}</div>
    </div>
  );
}

function SynthesisView({ data, onClose }: { data: any; onClose: () => void }) {
  return (
    <div className="card">
      <div className="row">
        <h3 style={{ margin: 0 }}>Comparison across {data.comparison?.length || 0} papers</h3>
        <span className="spacer" />
        <button className="btn ghost small" onClick={onClose}>Close</button>
      </div>
      {data.warnings?.length > 0 && (
        <div className="warning-box small">
          <ul>{data.warnings.map((w: string, i: number) => <li key={i}>{w}</li>)}</ul>
        </div>
      )}
      {data.overview && <p>{data.overview}</p>}

      <div className="table-wrap" style={{ marginBottom: 14 }}>
        <table>
          <thead>
            <tr>
              <th>Paper</th><th>Question</th><th>Model / system</th><th>Methods</th>
              <th>n</th><th>Intervention</th><th>Main findings</th><th>Limitations</th>
            </tr>
          </thead>
          <tbody>
            {(data.comparison || []).map((row: any, i: number) => (
              <tr key={i}>
                <td style={{ minWidth: 180 }}>
                  <strong>{row.title}</strong>
                  <div className="small muted">{row.year}</div>
                </td>
                <td>{row.research_question}</td>
                <td>{row.model_or_system}</td>
                <td>{row.methods}</td>
                <td>{row.sample_size}</td>
                <td>{row.intervention_or_exposure}</td>
                <td>{row.main_findings}</td>
                <td className="muted">{row.limitations}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {(data.contradictions || []).length > 0 && (
        <>
          <h4>Contradictions</h4>
          {data.contradictions.map((c: any, i: number) => (
            <div key={i} className="claim uncertain">
              <strong>{c.topic}</strong>
              {(c.positions || []).map((p: any, j: number) => (
                <div key={j} className="small">• {p.stance}</div>
              ))}
              {c.assessment && <div className="small muted" style={{ marginTop: 4 }}>{c.assessment}</div>}
            </div>
          ))}
        </>
      )}

      <div className="grid two">
        <div>
          <h4>Strongly supported</h4>
          {(data.strongly_supported || []).map((s: any, i: number) => (
            <div key={i} className="claim verified">
              {s.statement}
              <div className="small muted">{s.why}</div>
            </div>
          ))}
          {!(data.strongly_supported || []).length && (
            <p className="small muted">Nothing here is corroborated across independent sources.</p>
          )}
        </div>
        <div>
          <h4>Weakly supported</h4>
          {(data.weakly_supported || []).map((s: any, i: number) => (
            <div key={i} className="claim uncertain">
              {s.statement}
              <div className="small muted">{s.why}</div>
            </div>
          ))}
        </div>
      </div>

      {(data.research_gaps || []).length > 0 && (
        <>
          <h4>Research gaps</h4>
          <ul className="small">{data.research_gaps.map((g: string, i: number) => <li key={i}>{g}</li>)}</ul>
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ Chat */
export function ChatTab({
  messages, onFollowup, onExport, onSaveFinding, onAsk, busy, mode,
}: {
  messages: Message[];
  onFollowup: (q: string) => void;
  onExport: (messageId: string, format: string) => void;
  onSaveFinding: (claim: any) => void;
  onAsk: (question: string) => void;
  busy: boolean;
  mode: string;
}) {
  const bottom = useRef<HTMLDivElement>(null);
  const [draft, setDraft] = useState("");

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  const send = () => {
    const question = draft.trim();
    if (!question || busy) return;
    onAsk(question);
    setDraft("");
  };

  return (
    <div>
      {messages.length === 0 && (
        <Empty title="Nothing asked yet">
          <p>
            Ask below. Every question and answer is kept here with its sources, so a follow-up
            like “now only the last five years” refines what you already have instead of
            starting over.
          </p>
        </Empty>
      )}

      {messages.map((message) =>
        message.role === "user" ? (
          <div key={message.id} className="turn user">
            <div className="bubble">{message.content}</div>
          </div>
        ) : (
          <div key={message.id} className="turn">
            {message.answer ? (
              <AnswerView
                answer={message.answer as Answer}
                onFollowup={onFollowup}
                onExport={(format) => onExport(message.id, format)}
                onSaveFinding={onSaveFinding}
              />
            ) : (
              <div className="card">{message.content}</div>
            )}
          </div>
        ),
      )}

      {busy && (
        <div className="card">
          <Spinner label="Searching, reading and checking sources…" />
        </div>
      )}

      <div ref={bottom} />

      {/* The composer lives here as well as on Ask — a tab called Chat that you
          cannot type into is a dead end, which is exactly how it read on a phone. */}
      <div className="composer">
        <textarea
          rows={2}
          value={draft}
          placeholder="Ask a follow-up…"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
        />
        <div className="row" style={{ marginTop: 8 }}>
          <span className="small muted">
            Mode: <b>{mode.replace(/_/g, " ")}</b> — change it on the Ask tab
          </span>
          <span className="spacer" />
          <button className="btn primary" onClick={send} disabled={busy || !draft.trim()}>
            {busy ? <span className="spinner" /> : "Send"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ Files */
export function FilesTab({
  project, sources, reload, onFail,
}: {
  project: Project;
  sources: Source[];
  reload: () => void;
  onFail: Fail;
}) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [url, setUrl] = useState("");
  const [videoUrl, setVideoUrl] = useState("");
  const [urlResult, setUrlResult] = useState<any>(null);
  const [videoResult, setVideoResult] = useState<any>(null);
  const input = useRef<HTMLInputElement>(null);

  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true);
    try {
      setResult(await api.uploadFiles(project.id, [...files]));
      reload();
    } catch (error) {
      onFail(error);
    } finally {
      setBusy(false);
    }
  };

  const documents = sources.filter(
    (s) => s.kind !== "image" && (s.has_file || s.origin === "upload"),
  );

  return (
    <div>
      <div
        className="card"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          upload(e.dataTransfer.files);
        }}
        style={{ borderStyle: "dashed", textAlign: "center", padding: 28 }}
      >
        <h3 style={{ justifyContent: "center" }}>Drop papers, datasets or notes here</h3>
        <p className="small muted">
          PDF · DOCX · CSV · TSV · Excel · JSON · TXT · Markdown · images. Text is indexed
          immediately, so you can ask about it straight away.
        </p>
        <input
          ref={input} type="file" multiple hidden
          onChange={(e) => upload(e.target.files)}
        />
        <button className="btn primary" onClick={() => input.current?.click()} disabled={busy}>
          {busy ? <span className="spinner" /> : "Choose files"}
        </button>
      </div>

      {result && (
        <div className="card tight">
          <div className="small">{result.summary}</div>
          {result.failed?.map((f: any, i: number) => (
            <div key={i} className="small" style={{ color: "var(--critical)" }}>
              {f.filename}: {f.error}
            </div>
          ))}
        </div>
      )}

      <div className="grid two">
        <div className="card">
          <h3>Read a web page</h3>
          <p className="small muted" style={{ marginTop: -6 }}>
            Fetches the page (robots permitting), extracts its text, tables and references.
          </p>
          <div className="row">
            <input
              type="text" placeholder="https://…" value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
            <button
              className="btn"
              disabled={busy || !url.trim()}
              onClick={async () => {
                setBusy(true);
                try {
                  setUrlResult(await api.analyseUrl({ url, project_id: project.id }));
                  reload();
                } catch (error) {
                  onFail(error);
                } finally {
                  setBusy(false);
                }
              }}
            >
              Read
            </button>
          </div>
          {urlResult && <UrlResult data={urlResult} />}
        </div>

        <div className="card">
          <h3>Analyse a video</h3>
          <p className="small muted" style={{ marginTop: -6 }}>
            Uses the video's published captions. Videos without captions cannot be analysed.
          </p>
          <div className="row">
            <input
              type="text" placeholder="https://www.youtube.com/watch?v=…"
              value={videoUrl} onChange={(e) => setVideoUrl(e.target.value)}
            />
            <button
              className="btn"
              disabled={busy || !videoUrl.trim()}
              onClick={async () => {
                setBusy(true);
                try {
                  setVideoResult(await api.analyseVideo({ url: videoUrl, project_id: project.id }));
                  reload();
                } catch (error) {
                  onFail(error);
                } finally {
                  setBusy(false);
                }
              }}
            >
              Analyse
            </button>
          </div>
          {videoResult && <VideoResult data={videoResult} />}
        </div>
      </div>

      {documents.length > 0 && (
        <div className="card">
          <h3>Documents in this project</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>File</th><th>Kind</th><th>Passages</th><th /></tr>
              </thead>
              <tbody>
                {documents.map((doc) => (
                  <tr key={doc.id}>
                    <td>{doc.title}</td>
                    <td className="muted">{doc.kind.replace(/_/g, " ")}</td>
                    <td>{doc.passage_count ?? 0}</td>
                    <td>
                      <a className="btn ghost small" href={api.fileUrl(doc.id)} target="_blank" rel="noreferrer">
                        Open
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function UrlResult({ data }: { data: any }) {
  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ fontWeight: 600 }}>{data.source.title}</div>
      <div className="pill-row" style={{ margin: "6px 0" }}>
        <TierBadge tier={data.quality?.tier} />
        <span className="badge neutral">{data.content.word_count} words</span>
        {data.content.tables.length > 0 && (
          <span className="badge accent">{data.content.tables.length} tables</span>
        )}
        {data.content.references.length > 0 && (
          <span className="badge accent">{data.content.references.length} references</span>
        )}
      </div>
      <p className="small muted">{data.quality?.summary}</p>
      {data.content.tables.slice(0, 2).map((table: any, i: number) => (
        <div key={i} className="table-wrap" style={{ marginTop: 8, maxHeight: 220, overflowY: "auto" }}>
          <table>
            <thead><tr>{table.header.map((h: string, j: number) => <th key={j}>{h}</th>)}</tr></thead>
            <tbody>
              {table.rows.slice(0, 8).map((row: string[], j: number) => (
                <tr key={j}>{row.map((cell, k) => <td key={k}>{cell}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}

function VideoResult({ data }: { data: any }) {
  const analysis = data.analysis || {};
  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ fontWeight: 600 }}>{data.source.title}</div>
      {(analysis.warnings || []).map((w: string, i: number) => (
        <div key={i} className="warning-box small">{w}</div>
      ))}
      {analysis.summary && <p className="small">{analysis.summary}</p>}
      {(analysis.sections || []).length > 0 && (
        <>
          <h4>Sections</h4>
          {analysis.sections.map((s: any, i: number) => (
            <div key={i} className="small" style={{ marginBottom: 4 }}>
              {s.url ? (
                <a href={s.url} target="_blank" rel="noreferrer" className="mono">{s.timestamp}</a>
              ) : (
                <span className="mono muted">{s.timestamp}</span>
              )}{" "}
              <strong>{s.title}</strong> — {s.summary}
            </div>
          ))}
        </>
      )}
      {(analysis.questionable_claims || []).length > 0 && (
        <>
          <h4>Questionable claims</h4>
          {analysis.questionable_claims.map((c: any, i: number) => (
            <div key={i} className="claim uncertain">
              <div>{c.claim}</div>
              <div className="small muted">{c.why_questionable}</div>
            </div>
          ))}
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ Images */
export function ImagesTab({
  sources, onFail, hasVisionModel,
}: {
  sources: Source[];
  onFail: Fail;
  hasVisionModel: boolean;
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<any>(null);

  const images = sources.filter((s) => s.kind === "image");

  const toggle = (id: string) => {
    const next = new Set(selected);
    next.has(id) ? next.delete(id) : next.add(id);
    setSelected(next);
  };

  const run = async (compare: boolean) => {
    setBusy(true);
    setResult(null);
    try {
      const ids = [...selected];
      setResult(
        compare
          ? await api.compareImages(ids, question || undefined)
          : await api.analyseImage(ids[0], question || undefined),
      );
    } catch (error) {
      onFail(error);
    } finally {
      setBusy(false);
    }
  };

  if (!images.length) {
    return (
      <Empty title="No images yet">
        <p>
          Upload figures, blots, gels, microscopy, flow plots, charts or handwritten notes in the
          Files tab. Analysis keeps what is <em>visible</em> separate from what it might mean.
        </p>
      </Empty>
    );
  }

  // Say why a control is unavailable, on the control itself. A disabled button
  // with no explanation is indistinguishable from a broken one.
  const analyseBlocked = !hasVisionModel
    ? "Needs a vision model — set ANTHROPIC_API_KEY or OPENAI_API_KEY"
    : selected.size === 0
      ? "Select one image first"
      : selected.size > 1
        ? "Select exactly one image to analyse"
        : "";
  const compareBlocked = !hasVisionModel
    ? "Needs a vision model — set ANTHROPIC_API_KEY or OPENAI_API_KEY"
    : selected.size < 2
      ? "Select at least two images to compare"
      : "";

  return (
    <div>
      {!hasVisionModel && (
        <div className="warning-box">
          <strong>Image analysis is switched off</strong>
          <p style={{ margin: "4px 0 0" }}>
            Reading an image needs a vision-capable model, and none is configured. Set
            <code> ANTHROPIC_API_KEY</code> or <code> OPENAI_API_KEY</code> in your
            <code> .env</code> and restart. Your images stay in the project either way —
            nothing is lost. Search, papers, statistics and charts all work without it.
          </p>
        </div>
      )}

      <div className="card tight" style={{ marginBottom: 12 }}>
        <input
          type="text" placeholder="What do you want to know about these images?"
          value={question} onChange={(e) => setQuestion(e.target.value)}
        />
        <div className="row wrap" style={{ marginTop: 10, gap: 8 }}>
          <span className="small muted">
            {selected.size === 0
              ? "Tap an image below to select it"
              : `${selected.size} of ${images.length} selected`}
          </span>
          {selected.size > 0 && (
            <button className="btn ghost small" onClick={() => setSelected(new Set())}>
              Clear
            </button>
          )}
          {images.length > 1 && selected.size !== images.length && (
            <button
              className="btn ghost small"
              onClick={() => setSelected(new Set(images.map((i) => i.id)))}
            >
              Select all
            </button>
          )}
          <span className="spacer" />
          <button
            className="btn" disabled={busy || !!analyseBlocked}
            title={analyseBlocked} onClick={() => run(false)}
          >
            Analyse
          </button>
          <button
            className="btn" disabled={busy || !!compareBlocked}
            title={compareBlocked} onClick={() => run(true)}
          >
            Compare{selected.size > 1 ? ` ${selected.size}` : ""}
          </button>
        </div>
        {(analyseBlocked || compareBlocked) && !busy && (
          <div className="small muted" style={{ marginTop: 8 }}>
            {analyseBlocked && compareBlocked && analyseBlocked === compareBlocked
              ? analyseBlocked
              : [analyseBlocked && `Analyse: ${analyseBlocked}`,
                 compareBlocked && `Compare: ${compareBlocked}`]
                  .filter(Boolean)
                  .join(" · ")}
          </div>
        )}
        {busy && <div style={{ marginTop: 8 }}><Spinner label="Reading images…" /></div>}
      </div>

      <div className="grid three">
        {images.map((image, i) => {
          const isSelected = selected.has(image.id);
          return (
            <div
              key={image.id}
              className="card tight image-card"
              role="checkbox"
              aria-checked={isSelected}
              tabIndex={0}
              onClick={() => toggle(image.id)}
              onKeyDown={(e) => {
                if (e.key === " " || e.key === "Enter") {
                  e.preventDefault();
                  toggle(image.id);
                }
              }}
              style={{
                cursor: "pointer",
                borderColor: isSelected ? "var(--accent)" : undefined,
                boxShadow: isSelected ? "0 0 0 3px var(--accent-soft)" : undefined,
              }}
            >
              <div style={{ position: "relative" }}>
                <img
                  src={api.fileUrl(image.id)} alt={image.title}
                  style={{ width: "100%", borderRadius: 6, display: "block", background: "var(--surface-2)" }}
                />
                <span className={`select-dot ${isSelected ? "on" : ""}`} aria-hidden="true">
                  {isSelected ? "✓" : ""}
                </span>
              </div>
              <div className="small" style={{ marginTop: 6 }}>
                <span className="mono muted">IMG{i + 1}</span> {image.title}
              </div>
            </div>
          );
        })}
      </div>

      {result && <ImageResult data={result} />}
    </div>
  );
}

function ImageResult({ data }: { data: any }) {
  const list = (title: string, items: string[] | undefined, cls = "") =>
    items?.length ? (
      <>
        <h4>{title}</h4>
        <ul className={`small ${cls}`} style={{ margin: 0, paddingLeft: 18 }}>
          {items.map((x, i) => <li key={i}>{x}</li>)}
        </ul>
      </>
    ) : null;

  return (
    <div className="card">
      <h3>{data.per_image ? "Image comparison" : `Analysis — ${data.detected_kind || "image"}`}</h3>
      {data.disclaimer && <div className="note-box small">{data.disclaimer}</div>}

      {data.per_image && (
        <>
          {data.per_image.map((entry: any, i: number) => (
            <div key={i} style={{ marginBottom: 10 }}>
              <strong className="mono">{entry.image}</strong> — {entry.summary}
            </div>
          ))}
          {list("Common features", data.common_features)}
          {(data.differences || []).length > 0 && (
            <>
              <h4>Differences</h4>
              {data.differences.map((d: any, i: number) => (
                <div key={i} className="claim interpretation">
                  <strong>{d.aspect}</strong> ({d.image_a} vs {d.image_b}) — {d.difference}
                  <div className="small muted">confidence: {d.confidence}</div>
                </div>
              ))}
            </>
          )}
          {data.likely_relationship && (
            <>
              <h4>Likely relationship</h4>
              <p className="small">{data.likely_relationship}</p>
            </>
          )}
        </>
      )}

      {list("Observed (what is visible)", data.observations)}
      {list("Text read from the image", data.text_in_image)}
      {(data.measurements || []).length > 0 && (
        <>
          <h4>Measurements</h4>
          <div className="table-wrap">
            <table>
              <thead><tr><th>What</th><th>Value</th><th>Certainty</th></tr></thead>
              <tbody>
                {data.measurements.map((m: any, i: number) => (
                  <tr key={i}><td>{m.what}</td><td>{m.value}</td><td className="muted">{m.certainty}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {list("Interpretation (the model's reading)", data.interpretation)}
      {data.cannot_conclude?.length > 0 && (
        <div className="warning-box small" style={{ marginTop: 12 }}>
          <strong>What this image does not establish</strong>
          <ul>{data.cannot_conclude.map((x: string, i: number) => <li key={i}>{x}</li>)}</ul>
        </div>
      )}
      {list("Quality issues", data.quality_issues)}
    </div>
  );
}

/* ------------------------------------------------------------------ Data */
export function DataTab({
  project, sources, capabilities, onFail,
}: {
  project: Project;
  sources: Source[];
  capabilities: Capabilities | null;
  onFail: Fail;
}) {
  const datasets = sources.filter((s) => s.kind === "dataset");
  const [sourceId, setSourceId] = useState<string>(datasets[0]?.id || "");
  const [columns, setColumns] = useState<any[]>([]);
  const [profile, setProfile] = useState<any>(null);
  const [spec, setSpec] = useState<ChartSpec | null>(null);
  const [test, setTest] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState("bar");
  const [x, setX] = useState("");
  const [y, setY] = useState("");
  const [group, setGroup] = useState("");
  const [title, setTitle] = useState("");
  const [yUnit, setYUnit] = useState("");
  const [why, setWhy] = useState("");

  useEffect(() => {
    if (!sourceId) return;
    (async () => {
      try {
        const info = await api.datasetColumns(sourceId);
        setColumns(info.columns);
        setProfile(await api.analyse({ source_id: sourceId, operation: "profile" }));
      } catch (error) {
        onFail(error);
      }
    })();
  }, [sourceId]);

  const numericColumns = useMemo(() => columns.filter((c) => c.kind === "numeric"), [columns]);

  const build = async () => {
    setBusy(true);
    try {
      const body = {
        project_id: project.id, source_id: sourceId, form, x: x || null,
        y: y || null, group: group || null, title, y_unit: yUnit,
      };
      setSpec(await api.chart(body));
    } catch (error) {
      onFail(error);
    } finally {
      setBusy(false);
    }
  };

  const recommend = async () => {
    try {
      const result = await api.recommendChart({ source_id: sourceId, x: x || null, y: y || null, group: group || null });
      setForm(result.form);
      setWhy(result.why);
    } catch (error) {
      onFail(error);
    }
  };

  const runTest = async (operation: string) => {
    setBusy(true);
    try {
      setTest(
        await api.analyse({
          project_id: project.id, source_id: sourceId, operation,
          value_column: y || null, group_column: group || null, x: x || null, y: y || null,
        }),
      );
    } catch (error) {
      onFail(error);
    } finally {
      setBusy(false);
    }
  };

  if (!datasets.length) {
    return (
      <Empty title="No datasets yet">
        <p>Upload a CSV, TSV or Excel file in the Files tab and it becomes analysable here.</p>
      </Empty>
    );
  }

  return (
    <div>
      <div className="card">
        <div className="grid three">
          <label className="field">
            <span>Dataset</span>
            <select value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
              {datasets.map((d) => <option key={d.id} value={d.id}>{d.title}</option>)}
            </select>
          </label>
          <label className="field">
            <span>X / category</span>
            <select value={x} onChange={(e) => setX(e.target.value)}>
              <option value="">—</option>
              {columns.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
            </select>
          </label>
          <label className="field">
            <span>Y / value</span>
            <select value={y} onChange={(e) => setY(e.target.value)}>
              <option value="">—</option>
              {numericColumns.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
            </select>
          </label>
          <label className="field">
            <span>Group by</span>
            <select value={group} onChange={(e) => setGroup(e.target.value)}>
              <option value="">—</option>
              {columns.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
            </select>
          </label>
          <label className="field">
            <span>Chart form</span>
            <select value={form} onChange={(e) => setForm(e.target.value)}>
              {(capabilities?.chart_forms || []).map((f) => (
                <option key={f} value={f}>{f.replace(/_/g, " ")}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Y unit</span>
            <input type="text" value={yUnit} onChange={(e) => setYUnit(e.target.value)} placeholder="mm³" />
          </label>
        </div>
        <div className="row wrap" style={{ marginTop: 12, gap: 8 }}>
          <input
            type="text" placeholder="Figure title" value={title}
            onChange={(e) => setTitle(e.target.value)} style={{ maxWidth: 300 }}
          />
          <button className="btn ghost" onClick={recommend}>Suggest a form</button>
          <button className="btn primary" onClick={build} disabled={busy}>Plot</button>
          <span className="spacer" />
          <button className="btn small" disabled={!y || !group || busy} onClick={() => runTest("compare")}>
            Compare groups
          </button>
          <button className="btn small" disabled={!x || !y || busy} onClick={() => runTest("correlate")}>
            Correlate
          </button>
          <button className="btn small" disabled={!x || !y || busy} onClick={() => runTest("regress")}>
            Regress
          </button>
        </div>
        {why && <div className="note-box small" style={{ marginTop: 10 }}>{why}</div>}
      </div>

      {spec && (
        <div className="card">
          <Chart spec={spec} />
          <div className="pill-row" style={{ marginTop: 12 }}>
            {["png", "svg", "pdf"].map((fmt) => (
              <button
                key={fmt} className="btn small"
                onClick={() =>
                  api
                    .renderChart(
                      { source_id: sourceId, form, x: x || null, y: y || null, group: group || null, title, y_unit: yUnit },
                      fmt,
                    )
                    .catch(onFail)
                }
              >
                Export {fmt.toUpperCase()}
              </button>
            ))}
          </div>
        </div>
      )}

      {test && <TestResult data={test} />}
      {profile && <DataProfile data={profile} />}
    </div>
  );
}

function TestResult({ data }: { data: any }) {
  return (
    <div className="card">
      <h3>{data.test}</h3>
      <div className="grid three" style={{ marginBottom: 12 }}>
        <div className="stat">
          <div className="value">{data.p_value < 0.001 ? "<0.001" : Number(data.p_value).toPrecision(3)}</div>
          <div className="label">p-value</div>
        </div>
        <div className="stat">
          <div className="value">{data.statistic}</div>
          <div className="label">statistic</div>
        </div>
        <div className="stat">
          <div className="value">
            {data.effect?.cohens_d ?? data.effect?.r ?? data.effect?.r_squared ?? data.effect?.eta_squared ?? "—"}
          </div>
          <div className="label">effect size</div>
        </div>
      </div>
      <p>{data.interpretation}</p>

      <h4>Assumptions</h4>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Assumption</th><th>Test</th><th>p</th><th>Verdict</th></tr></thead>
          <tbody>
            {(data.assumptions || []).map((a: any, i: number) => (
              <tr key={i}>
                <td>{a.assumption}</td>
                <td className="muted">{a.test || "not tested"}</td>
                <td className="mono">{a.p_value != null ? Number(a.p_value).toPrecision(3) : "—"}</td>
                <td className="muted">{a.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {(data.warnings || []).length > 0 && (
        <div className="warning-box small" style={{ marginTop: 12 }}>
          <ul>{data.warnings.map((w: string, i: number) => <li key={i}>{w}</li>)}</ul>
        </div>
      )}
      {data.reproducible_code && (
        <>
          <h4>Reproduce this</h4>
          <pre className="code">{data.reproducible_code}</pre>
        </>
      )}
    </div>
  );
}

function DataProfile({ data }: { data: any }) {
  return (
    <div className="card">
      <h3>Dataset profile</h3>
      <div className="grid three" style={{ marginBottom: 12 }}>
        <div className="stat"><div className="value">{data.rows}</div><div className="label">rows</div></div>
        <div className="stat"><div className="value">{data.column_count}</div><div className="label">columns</div></div>
        <div className="stat"><div className="value">{data.missing_pct}%</div><div className="label">missing cells</div></div>
      </div>
      {(data.notes || []).map((note: string, i: number) => (
        <div key={i} className="note-box small">{note}</div>
      ))}
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>Column</th><th>Kind</th><th>Missing</th><th>Mean</th><th>SD</th><th>Outliers</th><th>Normality</th></tr>
          </thead>
          <tbody>
            {(data.columns || []).map((column: any) => (
              <tr key={column.name}>
                <td><strong>{column.name}</strong></td>
                <td className="muted">{column.kind}</td>
                <td>{column.missing ? `${column.missing} (${column.missing_pct}%)` : "—"}</td>
                <td className="mono">{column.mean ?? "—"}</td>
                <td className="mono">{column.sd ?? "—"}</td>
                <td>{column.outlier_count ?? "—"}</td>
                <td className="muted small">{column.normality?.note || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ Canvas */
export function CanvasTab({
  project, sources, onFail,
}: {
  project: Project;
  sources: Source[];
  onFail: Fail;
}) {
  const [description, setDescription] = useState("");
  const [kind, setKind] = useState("mechanism");
  const [kinds, setKinds] = useState<{ id: string; label: string }[]>([]);
  const [diagram, setDiagram] = useState<Diagram | null>(null);
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false);
  const [useSources, setUseSources] = useState(true);
  const [saved, setSaved] = useState<any[]>([]);

  useEffect(() => {
    api.diagramKinds().then((d) => setKinds(d.kinds)).catch(() => {});
    api.artifacts(project.id, "diagram").then((d) => setSaved(d.items)).catch(() => {});
  }, [project.id]);

  const create = async () => {
    setBusy(true);
    try {
      setDiagram(
        await api.createDiagram({
          description, kind, project_id: project.id,
          source_ids: useSources ? sources.slice(0, 6).map((s) => s.id) : [],
        }),
      );
    } catch (error) {
      onFail(error);
    } finally {
      setBusy(false);
    }
  };

  const revise = async () => {
    if (!diagram) return;
    setBusy(true);
    try {
      setDiagram(await api.reviseDiagram(diagram.id, instruction));
      setInstruction("");
    } catch (error) {
      onFail(error);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <div className="card">
        <h3>Describe the diagram you need</h3>
        <textarea
          rows={3}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Create a diagram showing the mechanism of CRISPR-Cas9 gene editing, from guide RNA binding through to repair."
        />
        <div className="row wrap" style={{ marginTop: 10, gap: 8 }}>
          <select value={kind} onChange={(e) => setKind(e.target.value)} style={{ maxWidth: 240 }}>
            {kinds.map((k) => <option key={k.id} value={k.id}>{k.label}</option>)}
          </select>
          <label className="checkbox">
            <input type="checkbox" checked={useSources} onChange={(e) => setUseSources(e.target.checked)} />
            Ground it in this project's sources
          </label>
          <span className="spacer" />
          <button className="btn primary" onClick={create} disabled={busy || !description.trim()}>
            {busy ? <span className="spinner" /> : "Draw"}
          </button>
        </div>
      </div>

      {diagram && (
        <div className="card">
          <div className="row" style={{ marginBottom: 8 }}>
            <h3 style={{ margin: 0 }}>{diagram.title}</h3>
            <span className="spacer" />
            <span className="badge neutral">
              revision {diagram.revision} · {diagram.node_count} nodes · {diagram.edge_count} edges
            </span>
          </div>
          <Mermaid source={diagram.source} />
          <div className="row" style={{ marginTop: 12 }}>
            <input
              type="text"
              placeholder="Add a step for repair · make it simpler · label every arrow"
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && revise()}
            />
            <button className="btn" onClick={revise} disabled={busy || !instruction.trim()}>
              Revise
            </button>
          </div>
          <details style={{ marginTop: 10 }}>
            <summary className="small muted" style={{ cursor: "pointer" }}>Mermaid source</summary>
            <pre className="code" style={{ marginTop: 8 }}>{diagram.source}</pre>
          </details>
        </div>
      )}

      {saved.length > 0 && (
        <div className="card">
          <h3>Saved diagrams</h3>
          <div className="pill-row">
            {saved.map((artifact) => (
              <button
                key={artifact.id} className="chip"
                onClick={() => setDiagram(artifact.payload)}
              >
                {artifact.title}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Mermaid({ source }: { source: string }) {
  const host = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        const dark = document.documentElement.dataset.theme === "dark";
        mermaid.initialize({
          startOnLoad: false,
          theme: dark ? "dark" : "neutral",
          securityLevel: "strict",
          fontFamily: "system-ui, -apple-system, sans-serif",
        });
        const { svg } = await mermaid.render(`m${Math.random().toString(36).slice(2)}`, source);
        if (!cancelled && host.current) {
          host.current.innerHTML = svg;
          setError(null);
        }
      } catch (exc) {
        if (!cancelled) setError(String(exc));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [source]);

  return (
    <>
      <div className="mermaid-host" ref={host} />
      {error && (
        <div className="warning-box small">
          This diagram could not be rendered: {error}
        </div>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ Notes */
export function NotesTab({
  project, notes, reload, onFail,
}: {
  project: Project;
  notes: Note[];
  reload: () => void;
  onFail: Fail;
}) {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");

  const save = async () => {
    try {
      await api.createNote(project.id, { title, body });
      setTitle("");
      setBody("");
      reload();
    } catch (error) {
      onFail(error);
    }
  };

  return (
    <div>
      <div className="card">
        <input
          type="text" placeholder="Note title" value={title}
          onChange={(e) => setTitle(e.target.value)} style={{ marginBottom: 8 }}
        />
        <textarea
          rows={4} placeholder="What did you notice?" value={body}
          onChange={(e) => setBody(e.target.value)}
        />
        <div className="row" style={{ marginTop: 8 }}>
          <span className="spacer" />
          <button className="btn primary" onClick={save} disabled={!body.trim() && !title.trim()}>
            Save note
          </button>
        </div>
      </div>
      {notes.map((note) => (
        <div key={note.id} className="card">
          <div className="row">
            <strong>{note.title || "Untitled note"}</strong>
            <span className="spacer" />
            <span className="muted small">{new Date(note.updated_at).toLocaleString()}</span>
            <button
              className="btn ghost small danger"
              onClick={async () => {
                try {
                  await api.deleteNote(project.id, note.id);
                  reload();
                } catch (error) {
                  onFail(error);
                }
              }}
            >
              Delete
            </button>
          </div>
          <p style={{ whiteSpace: "pre-wrap", marginBottom: 0 }}>{note.body}</p>
        </div>
      ))}
      {!notes.length && <Empty title="No notes yet" />}
    </div>
  );
}

/* ------------------------------------------------------------------ Citations */
export function CitationsTab({
  project, sources, style, onStyleChange, capabilities, onFail,
}: {
  project: Project;
  sources: Source[];
  style: string;
  onStyleChange: (style: string) => void;
  capabilities: Capabilities | null;
  onFail: Fail;
}) {
  const [data, setData] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!sources.length) return;
    setBusy(true);
    api
      .formatCitations({ project_id: project.id, style })
      .then(setData)
      .catch(onFail)
      .finally(() => setBusy(false));
  }, [project.id, style, sources.length]);

  if (!sources.length) return <Empty title="No sources to cite yet" />;

  return (
    <div>
      <div className="row wrap" style={{ marginBottom: 14, gap: 8 }}>
        <select value={style} onChange={(e) => onStyleChange(e.target.value)} style={{ maxWidth: 300 }}>
          {(capabilities?.citation_styles || []).map((s) => (
            <option key={s.id} value={s.id}>{s.label}</option>
          ))}
        </select>
        <span className="spacer" />
        <button
          className="btn"
          onClick={() => api.exportCitations({ project_id: project.id, style }, "bibtex").catch(onFail)}
        >
          Download .bib
        </button>
        <button
          className="btn"
          onClick={() => api.exportCitations({ project_id: project.id, style }, "ris").catch(onFail)}
        >
          Download .ris
        </button>
        <button
          className="btn ghost"
          onClick={() => navigator.clipboard.writeText(data?.bibliography || "")}
        >
          Copy bibliography
        </button>
      </div>

      {busy && <Spinner />}

      {data && (
        <>
          <div className="card">
            <h3>Bibliography</h3>
            <pre className="code" style={{ whiteSpace: "pre-wrap" }}>{data.bibliography}</pre>
          </div>
          {data.items.map((item: any) => (
            <div key={item.source_id} className="card tight">
              <div style={{ fontWeight: 550, marginBottom: 6 }}>{item.title}</div>
              <div className="small" style={{ marginBottom: 6 }}>{item.citation}</div>
              <div className="pill-row small">
                <span className="badge neutral">in-text: {item.in_text}</span>
                <button
                  className="btn ghost small"
                  onClick={() => navigator.clipboard.writeText(item.citation)}
                >
                  Copy
                </button>
                <button
                  className="btn ghost small"
                  onClick={() => navigator.clipboard.writeText(item.all_styles.bibtex)}
                >
                  Copy BibTeX
                </button>
              </div>
            </div>
          ))}
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ Map */
export function MapTab({ project, onFail }: { project: Project; onFail: Fail }) {
  const [graph, setGraph] = useState<Graph | null>(null);
  const [focus, setFocus] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);

  const load = (node?: string) => {
    setBusy(true);
    api
      .graph(project.id, node)
      .then(setGraph)
      .catch(onFail)
      .finally(() => setBusy(false));
  };

  useEffect(() => load(), [project.id]);

  if (busy && !graph) return <Spinner label="Building the research map…" />;
  if (!graph || !graph.nodes.length) {
    return (
      <Empty title="The map is empty">
        <p>Collect a few sources and the map draws itself: topics, papers, authors, methods and findings, connected.</p>
      </Empty>
    );
  }

  const colors: Record<string, string> = {
    question: "#4a3aa7", topic: "#2a78d6", paper: "#1baf7a", author: "#eb6834",
    venue: "#eda100", method: "#e87ba4", finding: "#008300", concept: "#e34948",
  };

  const width = 900;
  const height = 560;
  const centre = { x: width / 2, y: height / 2 };
  // Deterministic ring layout: a graph looks the same every time you open it.
  const byKind = new Map<string, typeof graph.nodes>();
  graph.nodes.forEach((node) => {
    byKind.set(node.kind, [...(byKind.get(node.kind) || []), node]);
  });
  const kinds = [...byKind.keys()];
  const positions = new Map<string, { x: number; y: number }>();
  kinds.forEach((kind, ringIndex) => {
    const nodes = byKind.get(kind)!;
    const radius = 60 + (ringIndex + 1) * (Math.min(width, height) / 2 / (kinds.length + 1));
    nodes.forEach((node, i) => {
      const angle = (i / nodes.length) * Math.PI * 2 + ringIndex * 0.6;
      positions.set(node.id, {
        x: centre.x + Math.cos(angle) * radius,
        y: centre.y + Math.sin(angle) * radius * 0.82,
      });
    });
  });

  return (
    <div>
      <div className="row wrap" style={{ marginBottom: 12, gap: 8 }}>
        {focus && (
          <button className="btn ghost small" onClick={() => { setFocus(null); load(); }}>
            ← Whole map
          </button>
        )}
        <span className="muted small">
          {graph.stats.nodes} nodes · {graph.stats.edges} edges
        </span>
        <span className="spacer" />
        <div className="pill-row small">
          {Object.entries(graph.stats.by_kind).map(([kind, count]) => (
            <span key={kind} className="row" style={{ gap: 5 }}>
              <span style={{ width: 9, height: 9, borderRadius: 9, background: colors[kind] || "#898781" }} />
              {kind} {count}
            </span>
          ))}
        </div>
      </div>

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", display: "block" }}>
          {graph.edges.map((edge, i) => {
            const a = positions.get(edge.source);
            const b = positions.get(edge.target);
            if (!a || !b) return null;
            return (
              <line
                key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                stroke="var(--border)" strokeWidth={Math.min(0.6 + edge.weight * 0.4, 3)}
              />
            );
          })}
          {graph.nodes.map((node) => {
            const point = positions.get(node.id);
            if (!point) return null;
            const radius = 5 + Math.min(node.weight, 6) * 1.6;
            return (
              <g
                key={node.id}
                style={{ cursor: "pointer" }}
                onClick={() => { setFocus(node.id); load(node.id); }}
              >
                <title>{node.detail || node.label}</title>
                <circle
                  cx={point.x} cy={point.y} r={radius}
                  fill={colors[node.kind] || "#898781"}
                  stroke="var(--surface-1)" strokeWidth={2}
                />
                {(node.weight > 1 || ["paper", "question", "finding"].includes(node.kind)) && (
                  <text
                    x={point.x} y={point.y - radius - 5} textAnchor="middle"
                    fontSize={10} fill="var(--text-2)"
                  >
                    {node.label.length > 22 ? node.label.slice(0, 21) + "…" : node.label}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      </div>
      <p className="small muted">
        Click a node to explore its neighbourhood. Nodes are built from retrieved metadata and
        verified findings — nothing here is invented to fill the picture out.
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ Providers */
export function ProvidersTab({ report }: { report: any }) {
  if (!report) return <Spinner />;
  return (
    <div>
      <p className="muted">
        What this deployment can actually do right now. Anything unavailable is reported in
        answers rather than worked around silently.
      </p>
      {Object.entries(report.capabilities).map(([capability, info]: [string, any]) => (
        <div key={capability} className="card">
          <div className="row">
            <h3 style={{ margin: 0 }}>{capability.replace(/_/g, " ")}</h3>
            <span className="spacer" />
            {info.available ? (
              <span className="badge verified">using {info.active}</span>
            ) : (
              <span className="badge critical">unavailable</span>
            )}
          </div>
          <div className="table-wrap" style={{ marginTop: 10 }}>
            <table>
              <thead><tr><th>Provider</th><th>Status</th><th>Detail</th></tr></thead>
              <tbody>
                {info.providers.map((provider: any) => (
                  <tr key={provider.name}>
                    <td><strong>{provider.name}</strong></td>
                    <td>
                      {provider.available ? (
                        <span className="badge verified">ready</span>
                      ) : (
                        <span className="badge neutral">off</span>
                      )}
                    </td>
                    <td className="muted small">
                      {provider.reason ||
                        Object.entries(provider)
                          .filter(([k]) => !["capability", "name", "available", "reason", "requires_credentials"].includes(k))
                          .map(([k, v]) => `${k}: ${v}`)
                          .join(" · ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </div>
  );
}

export function describeError(error: unknown): string {
  if (error instanceof WorkspaceApiError) return error.message;
  if (error instanceof Error) return error.message;
  return String(error);
}

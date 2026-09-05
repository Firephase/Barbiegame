import { useEffect, useRef, useState } from "react";
import type { Capabilities, Controls, ResearchMode } from "../types";

const DEFAULT_CONTROLS: Controls = {
  max_sources: 12,
  date_from: null,
  date_to: null,
  source_types: [],
  academic_only: false,
  web_only: false,
  open_access_only: false,
  include_preprints: true,
  language: null,
  region: null,
  domains_include: [],
  domains_exclude: [],
};

export { DEFAULT_CONTROLS };

/**
 * The one input the whole product hangs off: a question, a mode, and the
 * research controls the user is entitled to set (spec §20).
 */
export function AskBar({
  capabilities,
  mode,
  onModeChange,
  controls,
  onControlsChange,
  depth,
  onDepthChange,
  level,
  onLevelChange,
  onAsk,
  busy,
  hasReasoningModel,
  placeholder,
  seed,
}: {
  capabilities: Capabilities | null;
  mode: string;
  onModeChange: (mode: string) => void;
  controls: Controls;
  onControlsChange: (controls: Controls) => void;
  depth: string;
  onDepthChange: (depth: string) => void;
  level: string;
  onLevelChange: (level: string) => void;
  onAsk: (question: string) => void;
  busy: boolean;
  hasReasoningModel: boolean;
  placeholder?: string;
  seed?: string;
}) {
  const [text, setText] = useState("");
  const [showControls, setShowControls] = useState(false);
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (seed) {
      setText(seed);
      ref.current?.focus();
    }
  }, [seed]);

  const submit = () => {
    const question = text.trim();
    if (!question || busy) return;
    onAsk(question);
    setText("");
  };

  const modes: ResearchMode[] = capabilities?.modes || [];
  const patch = (change: Partial<Controls>) => onControlsChange({ ...controls, ...change });

  return (
    <div className="ask" style={{ marginBottom: 18 }}>
      <textarea
        ref={ref}
        value={text}
        placeholder={
          placeholder ||
          "Ask anything — or paste a URL, a DOI, or a video link. Try: “Find recent research on CRISPR-based cancer therapy and show where studies disagree.”"
        }
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            submit();
          }
        }}
        rows={2}
      />
      <div className="ask-foot">
        <div className="mode-chips">
          {modes.map((m) => {
            const locked = m.requires_reasoning_model && !hasReasoningModel;
            return (
              <button
                key={m.name}
                className={`chip ${mode === m.name ? "active" : ""} ${locked ? "locked" : ""}`}
                title={
                  locked
                    ? `${m.description} — needs a reasoning model (set ANTHROPIC_API_KEY or OPENAI_API_KEY).`
                    : m.description
                }
                onClick={() => !locked && onModeChange(m.name)}
                disabled={locked}
              >
                {m.label}
              </button>
            );
          })}
        </div>
        <span className="spacer" />
        <button className="btn ghost small" onClick={() => setShowControls((v) => !v)}>
          {showControls ? "Hide controls" : "Controls"}
        </button>
        <button className="btn primary" onClick={submit} disabled={busy || !text.trim()}>
          {busy ? <span className="spinner" /> : "Research"}
        </button>
      </div>

      {showControls && (
        <div style={{ padding: "14px 16px", borderTop: "1px solid var(--border)" }}>
          <div className="grid three">
            <label className="field">
              <span>Max sources</span>
              <input
                type="number"
                min={1}
                max={60}
                value={controls.max_sources}
                onChange={(e) => patch({ max_sources: Number(e.target.value) })}
              />
            </label>
            <label className="field">
              <span>Published from</span>
              <input
                type="date"
                value={controls.date_from || ""}
                onChange={(e) => patch({ date_from: e.target.value || null })}
              />
            </label>
            <label className="field">
              <span>Published to</span>
              <input
                type="date"
                value={controls.date_to || ""}
                onChange={(e) => patch({ date_to: e.target.value || null })}
              />
            </label>
            <label className="field">
              <span>Depth</span>
              <select value={depth} onChange={(e) => onDepthChange(e.target.value)}>
                {(capabilities?.depths || ["standard"]).map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Written for</span>
              <select value={level} onChange={(e) => onLevelChange(e.target.value)}>
                {(capabilities?.explanation_levels || []).map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Language</span>
              <input
                type="text"
                placeholder="any"
                value={controls.language || ""}
                onChange={(e) => patch({ language: e.target.value || null })}
              />
            </label>
          </div>

          <div className="row wrap" style={{ marginTop: 12, gap: 16 }}>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={controls.academic_only}
                onChange={(e) => patch({ academic_only: e.target.checked, web_only: false })}
              />
              Academic sources only
            </label>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={controls.web_only}
                onChange={(e) => patch({ web_only: e.target.checked, academic_only: false })}
              />
              Web only
            </label>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={controls.open_access_only}
                onChange={(e) => patch({ open_access_only: e.target.checked })}
              />
              Open access only
            </label>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={controls.include_preprints}
                onChange={(e) => patch({ include_preprints: e.target.checked })}
              />
              Include preprints
            </label>
          </div>

          <div className="grid two" style={{ marginTop: 12 }}>
            <label className="field">
              <span>Only these domains (comma separated)</span>
              <input
                type="text"
                placeholder="nih.gov, nature.com"
                value={controls.domains_include.join(", ")}
                onChange={(e) =>
                  patch({
                    domains_include: e.target.value
                      .split(",")
                      .map((s) => s.trim())
                      .filter(Boolean),
                  })
                }
              />
            </label>
            <label className="field">
              <span>Exclude these domains</span>
              <input
                type="text"
                value={controls.domains_exclude.join(", ")}
                onChange={(e) =>
                  patch({
                    domains_exclude: e.target.value
                      .split(",")
                      .map((s) => s.trim())
                      .filter(Boolean),
                  })
                }
              />
            </label>
          </div>
        </div>
      )}
    </div>
  );
}

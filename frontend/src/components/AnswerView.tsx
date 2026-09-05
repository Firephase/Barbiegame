import { useState } from "react";
import type { Answer, Claim, Source } from "../types";
import { StatusBadge, TierBadge, sourceLine } from "./common";
import { TracePanel } from "./TracePanel";

/**
 * The answer, rendered so that the three product questions are always on screen:
 * what did you find (the claims), where did it come from (the citation chips and
 * source list), and how certain are we (the epistemic badge on every claim, plus
 * the warnings banner and the confidence strip).
 */
export function AnswerView({
  answer,
  onFollowup,
  onExport,
  onSaveFinding,
}: {
  answer: Answer;
  onFollowup?: (question: string) => void;
  onExport?: (format: string) => void;
  onSaveFinding?: (claim: Claim) => void;
}) {
  const [openSource, setOpenSource] = useState<Source | null>(null);
  const sourceIndex = new Map(answer.sources.map((s, i) => [s.id, i + 1]));

  return (
    <div>
      {answer.warnings.length > 0 && (
        <div className="warning-box">
          <strong>Before you read this</strong>
          <ul>
            {answer.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      <ConfidenceStrip answer={answer} />

      {answer.summary && (
        <div className="card">
          <h3>Summary</h3>
          <p style={{ margin: 0, fontSize: 15, lineHeight: 1.6 }}>{answer.summary}</p>
        </div>
      )}

      {answer.claims.length > 0 && (
        <div className="card">
          <h3>
            Findings{" "}
            <span className="muted small" style={{ fontWeight: 400 }}>
              — every statement labelled by how it was established
            </span>
          </h3>
          {answer.claims.map((claim) => (
            <ClaimRow
              key={claim.id}
              claim={claim}
              answer={answer}
              index={sourceIndex}
              onOpenSource={setOpenSource}
              onSave={onSaveFinding}
            />
          ))}
        </div>
      )}

      {answer.disagreements.length > 0 && (
        <div className="card">
          <h3>Where sources disagree</h3>
          <p className="small muted" style={{ marginTop: -4 }}>
            These conflicts are shown rather than resolved — the underlying studies differ, and
            that difference is itself the finding.
          </p>
          {answer.disagreements.map((d, i) => (
            <div key={i} style={{ marginBottom: 14 }}>
              <div style={{ fontWeight: 600, marginBottom: 6 }}>{d.topic}</div>
              {d.positions.map((p, j) => (
                <div key={j} className="claim uncertain" style={{ marginBottom: 6 }}>
                  <div style={{ fontWeight: 550 }}>{p.stance}</div>
                  <div className="small muted">
                    {p.source_ids.map((sid) => {
                      const source = answer.sources.find((s) => s.id === sid);
                      return source ? (
                        <button
                          key={sid}
                          className="cite-ref"
                          onClick={() => setOpenSource(source)}
                          title={source.title}
                        >
                          S{sourceIndex.get(sid)}
                        </button>
                      ) : null;
                    })}{" "}
                    {p.note}
                  </div>
                </div>
              ))}
              {d.assessment && <p className="small muted">{d.assessment}</p>}
            </div>
          ))}
        </div>
      )}

      {answer.open_questions.length > 0 && (
        <div className="card">
          <h3>Open questions</h3>
          <ul style={{ margin: 0, paddingLeft: 20 }}>
            {answer.open_questions.map((q, i) => (
              <li key={i} style={{ marginBottom: 4 }}>
                {onFollowup ? (
                  <button className="btn ghost small" onClick={() => onFollowup(q)}>
                    {q}
                  </button>
                ) : (
                  q
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="card">
        <h3>Sources ({answer.sources.length})</h3>
        {answer.sources.map((source, i) => (
          <div
            key={source.id}
            className="source-card"
            style={{ cursor: "pointer" }}
            onClick={() => setOpenSource(source)}
          >
            <div className="row" style={{ alignItems: "flex-start", gap: 10 }}>
              <span className="mono muted" style={{ paddingTop: 2 }}>
                S{i + 1}
              </span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="title">{source.title}</div>
                <div className="meta">{sourceLine(source)}</div>
                <div className="pill-row">
                  <TierBadge tier={source.quality?.tier} />
                  {source.retracted && <span className="badge critical">Retracted</span>}
                  {source.is_peer_reviewed === false && (
                    <span className="badge uncertain">Not peer reviewed</span>
                  )}
                  {!source.full_text_retrieved && (
                    <span className="badge neutral">Abstract only</span>
                  )}
                  {source.is_open_access && <span className="badge accent">Open access</span>}
                  {typeof source.cited_by_count === "number" && (
                    <span className="badge neutral">{source.cited_by_count} citations</span>
                  )}
                </div>
                {answer.citations?.[source.id] && (
                  <div className="small muted" style={{ marginTop: 7 }}>
                    {answer.citations[source.id]}
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      <TracePanel answer={answer} />

      {(answer.followups?.length || onExport) && (
        <div className="card">
          {answer.followups && answer.followups.length > 0 && (
            <>
              <h4 style={{ marginTop: 0 }}>Where to go next</h4>
              <div className="pill-row" style={{ marginBottom: 14 }}>
                {answer.followups.map((f, i) => (
                  <button key={i} className="chip" onClick={() => onFollowup?.(f)}>
                    {f}
                  </button>
                ))}
              </div>
            </>
          )}
          {onExport && (
            <>
              <h4 style={{ marginTop: 0 }}>Export</h4>
              <div className="pill-row">
                {["pdf", "docx", "md", "xlsx", "pptx", "bibtex", "ris", "json"].map((f) => (
                  <button key={f} className="btn small" onClick={() => onExport(f)}>
                    {f.toUpperCase()}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {openSource && <SourceDrawer source={openSource} onClose={() => setOpenSource(null)} />}
    </div>
  );
}

function ConfidenceStrip({ answer }: { answer: Answer }) {
  const breakdown = answer.confidence_breakdown;
  if (!breakdown) return null;
  const total = Object.values(breakdown).reduce((a, b) => a + b, 0);
  if (!total) return null;
  const order: (keyof typeof breakdown)[] = [
    "verified", "interpretation", "uncertain", "ai_inference",
  ];
  const colors: Record<string, string> = {
    verified: "var(--verified)",
    interpretation: "var(--interpretation)",
    uncertain: "var(--uncertain)",
    ai_inference: "var(--inference)",
  };
  return (
    <div className="card tight" style={{ marginBottom: 14 }}>
      <div
        style={{
          display: "flex", height: 8, borderRadius: 4, overflow: "hidden",
          gap: 2, marginBottom: 8,
        }}
      >
        {order.map((k) =>
          breakdown[k] > 0 ? (
            <div
              key={k}
              style={{ flex: breakdown[k], background: colors[k] }}
              title={`${breakdown[k]} ${k.replace("_", " ")}`}
            />
          ) : null,
        )}
      </div>
      <div className="pill-row small">
        {order.map((k) =>
          breakdown[k] > 0 ? (
            <span key={k} className={`badge ${k}`}>
              {breakdown[k]} {k.replace("_", " ")}
            </span>
          ) : null,
        )}
        <span className="muted" style={{ marginLeft: "auto" }}>
          {answer.sources.length} source{answer.sources.length === 1 ? "" : "s"} · {answer.mode.replace("_", " ")}
        </span>
      </div>
    </div>
  );
}

function ClaimRow({
  claim,
  answer,
  index,
  onOpenSource,
  onSave,
}: {
  claim: Claim;
  answer: Answer;
  index: Map<string, number>;
  onOpenSource: (s: Source) => void;
  onSave?: (c: Claim) => void;
}) {
  const [showEvidence, setShowEvidence] = useState(false);
  const hasQuotes = claim.citations.some((c) => c.quote);

  return (
    <div className={`claim ${claim.status}`}>
      <p className="claim-text">
        {claim.text}
        {claim.citations.map((citation, i) => {
          const source = answer.sources.find((s) => s.id === citation.source_id);
          if (!source) return null;
          return (
            <button
              key={i}
              className="cite-ref"
              onClick={() => onOpenSource(source)}
              title={source.title}
            >
              S{index.get(source.id)}
              {citation.locator ? ` ${citation.locator}` : ""}
            </button>
          );
        })}
      </p>
      <div className="row wrap small">
        <StatusBadge status={claim.status} />
        {typeof claim.support_score === "number" && (
          <span className="muted" title="Share of this statement's content words found in the cited passage.">
            {Math.round(claim.support_score * 100)}% wording overlap
          </span>
        )}
        {claim.contested_by.length > 0 && (
          <span className="badge critical">
            Contested by {claim.contested_by.length} other source
            {claim.contested_by.length === 1 ? "" : "s"}
          </span>
        )}
        {hasQuotes && (
          <button className="btn ghost small" onClick={() => setShowEvidence((v) => !v)}>
            {showEvidence ? "Hide evidence" : "Show evidence"}
          </button>
        )}
        {onSave && claim.status !== "ai_inference" && (
          <button className="btn ghost small" onClick={() => onSave(claim)} title="Keep as a project finding">
            Save
          </button>
        )}
      </div>
      {claim.verification_note && (
        <div className="small muted" style={{ marginTop: 5 }}>
          {claim.verification_note}
        </div>
      )}
      {showEvidence &&
        claim.citations.map((citation, i) => {
          const source = answer.sources.find((s) => s.id === citation.source_id);
          return citation.quote ? (
            <div key={i} className="quote">
              “{citation.quote}”
              <div className="small muted" style={{ fontStyle: "normal", marginTop: 3 }}>
                — {source?.title}
                {citation.locator ? `, ${citation.locator}` : ""}
              </div>
            </div>
          ) : null;
        })}
    </div>
  );
}

export function SourceDrawer({ source, onClose }: { source: Source; onClose: () => void }) {
  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        <div className="row" style={{ marginBottom: 12 }}>
          <TierBadge tier={source.quality?.tier} />
          <span className="spacer" />
          <button className="btn ghost small" onClick={onClose}>
            Close
          </button>
        </div>
        <h2 style={{ fontSize: 17, margin: "0 0 6px", lineHeight: 1.3 }}>{source.title}</h2>
        <div className="muted small" style={{ marginBottom: 12 }}>
          {sourceLine(source)}
        </div>

        <div className="pill-row" style={{ marginBottom: 14 }}>
          {source.doi && (
            <a className="badge accent" href={`https://doi.org/${source.doi}`} target="_blank" rel="noreferrer">
              DOI {source.doi}
            </a>
          )}
          {source.url && (
            <a className="badge accent" href={source.url} target="_blank" rel="noreferrer">
              Open source ↗
            </a>
          )}
          <span className="badge neutral">Found via {source.retrieved_by}</span>
        </div>

        {source.retrieval_note && (
          <div className="note-box small">{source.retrieval_note}</div>
        )}

        {source.quality && (
          <>
            <h4>Why this source is rated as it is</h4>
            <p className="small">{source.quality.summary}</p>
            <div style={{ marginTop: 8 }}>
              {source.quality.signals.map((signal, i) => (
                <div key={i} className="signal">
                  <div style={{ fontWeight: 550 }}>{signal.dimension}</div>
                  <div className={`verdict ${signal.verdict}`}>{signal.verdict}</div>
                  <div className="muted">{signal.explanation}</div>
                </div>
              ))}
            </div>
            {source.quality.caveats.length > 0 && (
              <div className="warning-box small" style={{ marginTop: 12 }}>
                <strong>Caveats</strong>
                <ul>
                  {source.quality.caveats.map((c, i) => (
                    <li key={i}>{c}</li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}

        {source.abstract && (
          <>
            <h4>Abstract</h4>
            <p className="small">{source.abstract}</p>
          </>
        )}
      </div>
    </div>
  );
}

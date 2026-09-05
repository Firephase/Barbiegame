import type { Answer } from "../types";

/**
 * "How did you reach this conclusion?" (spec §23).
 *
 * Collapsed by default so it never crowds the answer, but it contains the whole
 * audit: what was searched, what was found, what was rejected and why, which
 * providers were unavailable, what was assumed, and every step taken.
 */
export function TracePanel({ answer }: { answer: Answer }) {
  const { trace } = answer;
  return (
    <details className="trace" style={{ marginBottom: 14 }}>
      <summary>
        How did you reach this conclusion?
        <span className="muted small" style={{ fontWeight: 400, marginLeft: "auto" }}>
          {trace.sources_considered} considered · {trace.sources_selected.length} used ·{" "}
          {trace.steps.length} steps
        </span>
      </summary>
      <div>
        <div className="grid three" style={{ marginBottom: 16 }}>
          <div className="stat">
            <div className="value">{trace.sources_considered}</div>
            <div className="label">Sources considered</div>
          </div>
          <div className="stat">
            <div className="value">{trace.sources_selected.length}</div>
            <div className="label">Sources used</div>
          </div>
          <div className="stat">
            <div className="value">{trace.sources_rejected.length}</div>
            <div className="label">Filtered out</div>
          </div>
        </div>

        {trace.queries_issued.length > 0 && (
          <>
            <h4>Searches run</h4>
            <div className="pill-row">
              {trace.queries_issued.map((q, i) => (
                <span key={i} className="badge neutral">
                  {q}
                </span>
              ))}
            </div>
          </>
        )}

        <h4>Providers</h4>
        <div className="pill-row">
          {trace.providers_used.map((p, i) => (
            <span key={i} className="badge verified">
              {p}
            </span>
          ))}
          {trace.providers_unavailable.map((p, i) => (
            <span key={i} className="badge critical" title={p.reason}>
              {p.provider} unavailable
            </span>
          ))}
        </div>
        {trace.providers_unavailable.map((p, i) => (
          <div key={i} className="small muted" style={{ marginTop: 6 }}>
            <strong>{p.provider}:</strong> {p.reason}
          </div>
        ))}

        {trace.assumptions.length > 0 && (
          <>
            <h4>Assumptions made</h4>
            <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
              {trace.assumptions.map((a, i) => (
                <li key={i}>{a}</li>
              ))}
            </ul>
          </>
        )}

        {trace.limitations.length > 0 && (
          <>
            <h4>Limitations</h4>
            <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
              {trace.limitations.map((l, i) => (
                <li key={i}>{l}</li>
              ))}
            </ul>
          </>
        )}

        {trace.sources_rejected.length > 0 && (
          <>
            <h4>Sources filtered out</h4>
            <div className="table-wrap" style={{ maxHeight: 220, overflowY: "auto" }}>
              <table>
                <thead>
                  <tr>
                    <th>Source</th>
                    <th>Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {trace.sources_rejected.slice(0, 40).map((r, i) => (
                    <tr key={i}>
                      <td>{r.title}</td>
                      <td className="muted">{r.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}

        {trace.computations.length > 0 && (
          <>
            <h4>Calculations performed</h4>
            <pre className="code">{JSON.stringify(trace.computations, null, 2)}</pre>
          </>
        )}

        <h4>Steps</h4>
        <div>
          {trace.steps.map((step, i) => (
            <div key={i} className="step">
              <div className="stage">{step.stage}</div>
              <div>
                {step.detail}
                {step.duration_ms != null && (
                  <span className="muted small"> ({step.duration_ms} ms)</span>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </details>
  );
}

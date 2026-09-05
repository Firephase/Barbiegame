import { useMemo, useState } from "react";
import type { ChartSpec } from "../types";

/**
 * Interactive SVG renderer for a ChartSpec.
 *
 * The same spec is rendered server-side by matplotlib for export, so the screen
 * and the exported figure agree. Every form ships a hover layer, and any chart
 * whose palette needs relief also offers the table view — identity never rests
 * on colour alone.
 */
export function Chart({ spec }: { spec: ChartSpec }) {
  const [hover, setHover] = useState<{ x: number; y: number; label: string } | null>(null);
  const [showTable, setShowTable] = useState(false);

  const chrome = spec.palette.chrome;
  const W = 720;
  const H = 380;
  const pad = { top: 18, right: 22, bottom: 58, left: 62 };
  const plotW = W - pad.left - pad.right;
  const plotH = H - pad.top - pad.bottom;

  const numeric = useMemo(() => {
    const all = spec.series.flatMap((s) => s.y.filter((v) => typeof v === "number"));
    const errs = spec.series.flatMap((s) => s.error || []);
    const lo = all.length ? Math.min(...all) : 0;
    const hi = all.length ? Math.max(...all, ...errs.map((e, i) => (all[i] ?? 0) + e)) : 1;
    const span = hi - lo || 1;
    return { lo: Math.min(lo, 0) === 0 && lo >= 0 ? 0 : lo - span * 0.08, hi: hi + span * 0.08 };
  }, [spec]);

  const yScale = (value: number) =>
    pad.top + plotH - ((value - numeric.lo) / (numeric.hi - numeric.lo || 1)) * plotH;

  const ticks = useMemo(() => {
    const count = 5;
    return Array.from({ length: count + 1 }, (_, i) => {
      const value = numeric.lo + ((numeric.hi - numeric.lo) * i) / count;
      return { value, y: yScale(value) };
    });
  }, [numeric]);

  const isMatrix = spec.form === "heatmap" || spec.form === "correlation";
  const isCategorical = ["bar", "grouped_bar", "stacked_bar", "box", "violin"].includes(spec.form);

  return (
    <div>
      <div className="row" style={{ marginBottom: 6 }}>
        <div>
          {spec.title && <div style={{ fontWeight: 600, fontSize: 15 }}>{spec.title}</div>}
          {spec.subtitle && <div className="small muted">{spec.subtitle}</div>}
        </div>
        <span className="spacer" />
        {spec.table_view && (
          <button className="btn ghost small" onClick={() => setShowTable((v) => !v)}>
            {showTable ? "Chart" : "Table"}
          </button>
        )}
      </div>

      {showTable ? (
        <ChartTable spec={spec} />
      ) : isMatrix ? (
        <MatrixChart spec={spec} />
      ) : (
        <div style={{ position: "relative", overflowX: "auto" }}>
          <svg
            viewBox={`0 0 ${W} ${H}`}
            style={{ width: "100%", minWidth: 420, background: chrome.surface, borderRadius: 8 }}
            role="img"
            aria-label={spec.title || `${spec.form} chart`}
          >
            {/* gridlines stay recessive */}
            {ticks.map((tick, i) => (
              <g key={i}>
                <line
                  x1={pad.left} x2={W - pad.right} y1={tick.y} y2={tick.y}
                  stroke={chrome.grid} strokeWidth={1}
                />
                <text
                  x={pad.left - 8} y={tick.y + 4} textAnchor="end"
                  fontSize={11} fill={chrome.muted}
                >
                  {formatTick(tick.value)}
                </text>
              </g>
            ))}
            <line
              x1={pad.left} x2={pad.left} y1={pad.top} y2={pad.top + plotH}
              stroke={chrome.axis} strokeWidth={1}
            />
            <line
              x1={pad.left} x2={W - pad.right} y1={pad.top + plotH} y2={pad.top + plotH}
              stroke={chrome.axis} strokeWidth={1}
            />

            {isCategorical
              ? renderCategorical(spec, { pad, plotW, plotH, yScale, chrome, setHover })
              : renderContinuous(spec, { pad, plotW, plotH, yScale, chrome, setHover })}

            <text
              x={pad.left + plotW / 2} y={H - 12} textAnchor="middle"
              fontSize={12} fill={chrome.text_secondary}
            >
              {spec.x.unit ? `${spec.x.label} (${spec.x.unit})` : spec.x.label}
            </text>
            <text
              transform={`translate(14 ${pad.top + plotH / 2}) rotate(-90)`}
              textAnchor="middle" fontSize={12} fill={chrome.text_secondary}
            >
              {spec.y.unit ? `${spec.y.label} (${spec.y.unit})` : spec.y.label}
            </text>
          </svg>

          {hover && (
            <div
              style={{
                position: "absolute", left: `${(hover.x / W) * 100}%`,
                top: `${(hover.y / H) * 100}%`, transform: "translate(-50%, -130%)",
                background: "var(--surface-1)", border: "1px solid var(--border-strong)",
                borderRadius: 6, padding: "5px 9px", fontSize: 12, pointerEvents: "none",
                whiteSpace: "nowrap", boxShadow: "var(--shadow-1)", zIndex: 3,
              }}
            >
              {hover.label}
            </div>
          )}
        </div>
      )}

      {spec.legend && spec.series.length > 1 && (
        <div className="pill-row" style={{ marginTop: 10 }}>
          {spec.series.map((series) => (
            <span key={series.name} className="row small" style={{ gap: 6 }}>
              <span
                style={{
                  width: 10, height: 10, borderRadius: 3, background: series.color,
                  display: "inline-block",
                }}
              />
              {series.name}
            </span>
          ))}
        </div>
      )}

      {spec.caption && (
        <div className="small muted" style={{ marginTop: 8 }}>
          {spec.caption}
        </div>
      )}
      {spec.notes.map((note, i) => (
        <div key={i} className="small muted" style={{ marginTop: 4 }}>
          {note}
        </div>
      ))}
    </div>
  );
}

type RenderCtx = {
  pad: { top: number; right: number; bottom: number; left: number };
  plotW: number;
  plotH: number;
  yScale: (v: number) => number;
  chrome: Record<string, string>;
  setHover: (h: { x: number; y: number; label: string } | null) => void;
};

function renderCategorical(spec: ChartSpec, ctx: RenderCtx) {
  const { pad, plotW, plotH, yScale, chrome, setHover } = ctx;
  const isDistribution = spec.form === "box" || spec.form === "violin";
  const categories = isDistribution
    ? spec.series.map((s) => s.name)
    : spec.series[0]?.x.map(String) || [];
  const slot = plotW / Math.max(categories.length, 1);

  if (isDistribution) {
    return (
      <g>
        {spec.series.map((series, i) => {
          const values = [...series.y].sort((a, b) => a - b);
          if (!values.length) return null;
          const q = (p: number) => values[Math.min(Math.floor(p * values.length), values.length - 1)];
          const [lo, q1, med, q3, hi] = [values[0], q(0.25), q(0.5), q(0.75), values[values.length - 1]];
          const cx = pad.left + slot * (i + 0.5);
          const boxW = Math.min(slot * 0.5, 64);
          return (
            <g
              key={series.name}
              onMouseEnter={() =>
                setHover({
                  x: cx, y: yScale(med),
                  label: `${series.name}: median ${med.toFixed(2)} (IQR ${q1.toFixed(2)}–${q3.toFixed(2)}, n=${values.length})`,
                })
              }
              onMouseLeave={() => setHover(null)}
            >
              <line x1={cx} x2={cx} y1={yScale(hi)} y2={yScale(lo)} stroke={chrome.axis} strokeWidth={1} />
              <rect
                x={cx - boxW / 2} y={yScale(q3)} width={boxW} height={Math.max(yScale(q1) - yScale(q3), 1)}
                fill={series.color} opacity={0.85} rx={3}
                stroke={chrome.surface} strokeWidth={2}
              />
              <line
                x1={cx - boxW / 2} x2={cx + boxW / 2} y1={yScale(med)} y2={yScale(med)}
                stroke={chrome.text} strokeWidth={2}
              />
              {values.length <= 60 &&
                values.map((value, j) => (
                  <circle
                    key={j}
                    cx={cx + ((j % 7) - 3) * 3.2}
                    cy={yScale(value)}
                    r={2.1}
                    fill={chrome.text_secondary}
                    opacity={0.45}
                  />
                ))}
              <text
                x={cx} y={pad.top + plotH + 18} textAnchor="middle"
                fontSize={11} fill={chrome.muted}
              >
                {series.name}
              </text>
              <text
                x={cx} y={pad.top + plotH + 32} textAnchor="middle"
                fontSize={10} fill={chrome.muted}
              >
                n={values.length}
              </text>
            </g>
          );
        })}
      </g>
    );
  }

  const stacked = spec.form === "stacked_bar";
  const n = spec.series.length;
  const barW = stacked || n === 1 ? slot * 0.62 : (slot * 0.7) / n;
  const bottoms = new Array(categories.length).fill(0);

  return (
    <g>
      {spec.series.map((series, si) =>
        series.y.map((value, ci) => {
          const base = stacked ? bottoms[ci] : 0;
          const x = stacked || n === 1
            ? pad.left + slot * (ci + 0.5) - barW / 2
            : pad.left + slot * (ci + 0.5) - (barW * n) / 2 + barW * si;
          const top = yScale(base + value);
          const height = Math.max(yScale(base) - top, 1);
          if (stacked) bottoms[ci] = base + value;
          return (
            <g key={`${si}-${ci}`}>
              <rect
                x={x} y={top} width={barW} height={height}
                fill={series.color} rx={4}
                stroke={stacked ? spec.palette.chrome.surface : "none"}
                strokeWidth={stacked ? 2 : 0}
                onMouseEnter={() =>
                  setHover({
                    x: x + barW / 2, y: top,
                    label: `${categories[ci]} · ${series.name}: ${value}`,
                  })
                }
                onMouseLeave={() => setHover(null)}
              />
              {series.error?.[ci] != null && (
                <line
                  x1={x + barW / 2} x2={x + barW / 2}
                  y1={yScale(value - series.error[ci])} y2={yScale(value + series.error[ci])}
                  stroke={chrome.text_secondary} strokeWidth={1.2}
                />
              )}
              {spec.direct_labels && (
                <text
                  x={x + barW / 2} y={top - 5} textAnchor="middle"
                  fontSize={10} fill={chrome.text_secondary}
                >
                  {typeof value === "number" ? value.toPrecision(3) : value}
                </text>
              )}
            </g>
          );
        }),
      )}
      {categories.map((category, i) => (
        <text
          key={i}
          x={pad.left + slot * (i + 0.5)}
          y={pad.top + plotH + 18}
          textAnchor="middle"
          fontSize={11}
          fill={chrome.muted}
        >
          {category.length > 12 ? category.slice(0, 11) + "…" : category}
        </text>
      ))}
    </g>
  );
}

function renderContinuous(spec: ChartSpec, ctx: RenderCtx) {
  const { pad, plotW, plotH, yScale, chrome, setHover } = ctx;
  const allX = spec.series.flatMap((s) => s.x.map((v) => (typeof v === "number" ? v : NaN)));
  const numericX = allX.filter((v) => !Number.isNaN(v));
  const xLo = numericX.length ? Math.min(...numericX) : 0;
  const xHi = numericX.length ? Math.max(...numericX) : 1;

  const xScale = (value: string | number, index: number, length: number) =>
    typeof value === "number" && numericX.length
      ? pad.left + ((value - xLo) / (xHi - xLo || 1)) * plotW
      : pad.left + (length > 1 ? (index / (length - 1)) * plotW : plotW / 2);

  const isScatter = ["scatter", "pca", "volcano"].includes(spec.form);

  return (
    <g>
      {spec.series.map((series) => {
        const points = series.y.map((value, i) => ({
          cx: xScale(series.x[i], i, series.y.length),
          cy: yScale(value),
          value,
          x: series.x[i],
        }));
        if (isScatter) {
          return (
            <g key={series.name}>
              {points.map((point, i) => (
                <circle
                  key={i} cx={point.cx} cy={point.cy} r={4.5}
                  fill={series.color} stroke={chrome.surface} strokeWidth={1.5} opacity={0.92}
                  onMouseEnter={() =>
                    setHover({
                      x: point.cx, y: point.cy,
                      label: `${series.name}: (${fmt(point.x)}, ${fmt(point.value)})`,
                    })
                  }
                  onMouseLeave={() => setHover(null)}
                />
              ))}
            </g>
          );
        }
        if (spec.form === "histogram") {
          const bins = histogram(series.y, Math.max(Math.round(Math.sqrt(series.y.length)), 5));
          const barW = plotW / bins.length;
          const maxCount = Math.max(...bins.map((b) => b.count), 1);
          return (
            <g key={series.name}>
              {bins.map((bin, i) => {
                const height = (bin.count / maxCount) * plotH;
                return (
                  <rect
                    key={i}
                    x={pad.left + i * barW + 1}
                    y={pad.top + plotH - height}
                    width={barW - 2}
                    height={height}
                    fill={series.color}
                    opacity={spec.series.length > 1 ? 0.75 : 1}
                    rx={3}
                    onMouseEnter={() =>
                      setHover({
                        x: pad.left + i * barW + barW / 2,
                        y: pad.top + plotH - height,
                        label: `${bin.lo.toPrecision(3)}–${bin.hi.toPrecision(3)}: ${bin.count}`,
                      })
                    }
                    onMouseLeave={() => setHover(null)}
                  />
                );
              })}
            </g>
          );
        }
        const path = points
          .map((point, i) => `${i === 0 ? "M" : "L"}${point.cx},${point.cy}`)
          .join(" ");
        return (
          <g key={series.name}>
            <path d={path} fill="none" stroke={series.color} strokeWidth={2}
                  strokeLinejoin="round" strokeLinecap="round" />
            {points.map((point, i) => (
              <circle
                key={i} cx={point.cx} cy={point.cy} r={4}
                fill={series.color} stroke={chrome.surface} strokeWidth={1.5}
                onMouseEnter={() =>
                  setHover({
                    x: point.cx, y: point.cy,
                    label: `${series.name} · ${fmt(point.x)}: ${fmt(point.value)}`,
                  })
                }
                onMouseLeave={() => setHover(null)}
              />
            ))}
          </g>
        );
      })}
      {spec.series[0] && spec.form !== "histogram" && (
        <g>
          {[0, 0.5, 1].map((t, i) => {
            const value = xLo + (xHi - xLo) * t;
            return (
              <text
                key={i} x={pad.left + plotW * t} y={pad.top + plotH + 18}
                textAnchor="middle" fontSize={11} fill={chrome.muted}
              >
                {numericX.length ? formatTick(value) : String(spec.series[0].x[Math.floor(t * (spec.series[0].x.length - 1))] ?? "")}
              </text>
            );
          })}
        </g>
      )}
    </g>
  );
}

function MatrixChart({ spec }: { spec: ChartSpec }) {
  const rows = spec.matrix_rows || [];
  const cols = spec.matrix_cols || [];
  const matrix = spec.matrix || [];
  const cell = Math.max(Math.min(560 / Math.max(cols.length, 1), 56), 26);
  const limit = Math.max(
    ...matrix.flat().map((v) => Math.abs(v ?? 0)),
    0.0001,
  );

  const color = (value: number) => {
    if (spec.diverging) {
      const t = value / limit;
      const pole = t >= 0 ? spec.palette.diverging.high : spec.palette.diverging.low;
      return mix(spec.palette.diverging.mid, pole, Math.min(Math.abs(t), 1));
    }
    const ramp = spec.palette.sequential;
    return ramp[Math.min(Math.floor((value / limit) * (ramp.length - 1)), ramp.length - 1)];
  };

  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ borderCollapse: "separate", borderSpacing: 2, width: "auto" }}>
        <thead>
          <tr>
            <th style={{ background: "none", border: 0 }} />
            {cols.map((c) => (
              <th key={c} style={{ background: "none", border: 0, fontSize: 10, padding: 3 }}>
                <div style={{ writingMode: "vertical-rl", transform: "rotate(180deg)", maxHeight: 90 }}>
                  {c}
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={row}>
              <td style={{ border: 0, fontSize: 11, whiteSpace: "nowrap", paddingRight: 8 }}>{row}</td>
              {cols.map((_, j) => {
                const value = matrix[i]?.[j];
                return (
                  <td
                    key={j}
                    title={`${row} × ${cols[j]}: ${value ?? "—"}`}
                    style={{
                      width: cell, height: cell, border: 0, padding: 0, borderRadius: 4,
                      background: value == null ? "var(--surface-2)" : color(value),
                      textAlign: "center", fontSize: 10,
                      color: Math.abs(value ?? 0) > limit * 0.6 ? "#fff" : "var(--text-1)",
                    }}
                  >
                    {value == null ? "" : value.toFixed(2)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ChartTable({ spec }: { spec: ChartSpec }) {
  return (
    <div className="table-wrap" style={{ maxHeight: 380, overflowY: "auto" }}>
      <table>
        <thead>
          <tr>
            <th>{spec.x.label || "x"}</th>
            {spec.series.map((s) => (
              <th key={s.name}>{s.name}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {(spec.series[0]?.y || []).map((_, i) => (
            <tr key={i}>
              <td>{String(spec.series[0].x[i] ?? i + 1)}</td>
              {spec.series.map((s) => (
                <td key={s.name}>{fmt(s.y[i])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function fmt(value: unknown): string {
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toPrecision(4).replace(/\.?0+$/, "");
  }
  return String(value ?? "");
}

function formatTick(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1e6) return `${(value / 1e6).toPrecision(3)}M`;
  if (abs >= 1e4) return `${(value / 1e3).toPrecision(3)}k`;
  if (abs >= 1) return value.toFixed(abs < 10 ? 1 : 0);
  return value.toPrecision(2);
}

function histogram(values: number[], bins: number) {
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const width = (hi - lo) / bins || 1;
  return Array.from({ length: bins }, (_, i) => {
    const binLo = lo + i * width;
    const binHi = binLo + width;
    return {
      lo: binLo,
      hi: binHi,
      count: values.filter((v) => (i === bins - 1 ? v >= binLo && v <= binHi : v >= binLo && v < binHi))
        .length,
    };
  });
}

function mix(a: string, b: string, t: number): string {
  const parse = (hex: string) => {
    const clean = hex.replace("#", "");
    return [0, 2, 4].map((i) => parseInt(clean.slice(i, i + 2), 16));
  };
  const [r1, g1, b1] = parse(a);
  const [r2, g2, b2] = parse(b);
  const channel = (x: number, y: number) => Math.round(x + (y - x) * t);
  return `rgb(${channel(r1, r2)}, ${channel(g1, g2)}, ${channel(b1, b2)})`;
}

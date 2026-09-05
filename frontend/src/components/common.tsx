import type { ReactNode } from "react";
import type { Epistemic, Source } from "../types";

export const STATUS_LABEL: Record<Epistemic, string> = {
  verified: "Verified",
  interpretation: "Interpretation",
  uncertain: "Uncertain",
  ai_inference: "AI inference",
};

export const STATUS_GLYPH: Record<Epistemic, string> = {
  verified: "●",
  interpretation: "◐",
  uncertain: "◔",
  ai_inference: "○",
};

/** What each label actually means — shown on hover, so nothing rests on colour. */
export const STATUS_HELP: Record<Epistemic, string> = {
  verified:
    "A retrieved source states this, and the wording was checked against that source's text.",
  interpretation:
    "The retrieved sources support this, but the reading is the assistant's rather than a direct statement.",
  uncertain:
    "The evidence is thin, dated, or the sources disagree with each other.",
  ai_inference:
    "No retrieved passage supports this. It is the model's own reasoning — check it before relying on it.",
};

export function StatusBadge({ status }: { status: Epistemic }) {
  return (
    <span className={`badge ${status}`} title={STATUS_HELP[status]}>
      <span className="glyph" aria-hidden="true">{STATUS_GLYPH[status]}</span>
      {STATUS_LABEL[status]}
    </span>
  );
}

export function TierBadge({ tier }: { tier?: string | null }) {
  if (!tier) return null;
  return <span className={`tier ${tier}`}>{tier.replace(/_/g, " ")}</span>;
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="row small muted">
      <span className="spinner" /> {label || "Working…"}
    </span>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <h2>{title}</h2>
      {children}
    </div>
  );
}

export function sourceLine(source: Source): string {
  const authors =
    source.authors.length === 0
      ? "No named author"
      : source.authors.length > 3
        ? `${source.authors[0].name} et al.`
        : source.authors.map((a) => a.name).join(", ");
  const year = source.published ? new Date(source.published).getFullYear() : "undated";
  const venue = source.container_title || source.site_name || "";
  return [authors, year, venue].filter(Boolean).join(" · ");
}

export function formatSeconds(seconds?: number | null): string {
  if (seconds == null) return "";
  const total = Math.floor(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${m}:${String(s).padStart(2, "0")}`;
}

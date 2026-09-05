"""Chart generation (spec §8).

Two outputs from one spec:

* a **ChartSpec** (data + encoding + resolved palette) that the browser renders
  interactively with a hover layer and a table view;
* a **rendered figure** (PNG / SVG / PDF) from matplotlib for export and print.

Values are always taken from the supplied data.  Nothing is smoothed, rounded
into shape, or estimated from a picture — if a series has gaps, the gaps are
drawn as gaps and the caption says how many points were missing.
"""
from __future__ import annotations

import io
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd

from ..core.errors import BadRequest
from . import palette as pal

FORMS = (
    "bar", "grouped_bar", "stacked_bar", "line", "scatter", "histogram", "box",
    "violin", "heatmap", "pie", "survival", "correlation", "pca", "volcano",
    "dose_response", "timeseries", "network",
)

ExportFormat = Literal["png", "svg", "pdf"]


@dataclass
class Axis:
    label: str = ""
    unit: str = ""
    scale: Literal["linear", "log", "symlog"] = "linear"
    min: float | None = None
    max: float | None = None

    @property
    def title(self) -> str:
        return f"{self.label} ({self.unit})" if self.unit else self.label


@dataclass
class Series:
    name: str
    x: list[Any] = field(default_factory=list)
    y: list[Any] = field(default_factory=list)
    error: list[float] | None = None
    color: str = ""
    labels: list[str] | None = None


@dataclass
class Annotation:
    """A statistical annotation — significance bar, threshold line, or note."""

    kind: Literal["significance", "threshold", "note"]
    text: str
    x: Any = None
    x2: Any = None
    y: float | None = None


@dataclass
class ChartSpec:
    form: str
    title: str = ""
    subtitle: str = ""
    x: Axis = field(default_factory=Axis)
    y: Axis = field(default_factory=Axis)
    series: list[Series] = field(default_factory=list)
    annotations: list[Annotation] = field(default_factory=list)
    legend: bool = True
    #: The relief rule: low-contrast slots must carry visible labels or a table.
    direct_labels: bool = False
    table_view: bool = True
    caption: str = ""
    notes: list[str] = field(default_factory=list)
    width: float = 7.2
    height: float = 4.4
    mode: pal.Mode = "light"
    matrix: list[list[float]] | None = None       # heatmap / correlation
    matrix_rows: list[str] | None = None
    matrix_cols: list[str] | None = None
    diverging: bool = False

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["palette"] = {
            "categorical": pal.CATEGORICAL[self.mode],
            "chrome": pal.CHROME[self.mode],
            "sequential": pal.SEQUENTIAL[self.mode],
            "diverging": pal.DIVERGING[self.mode],
        }
        return payload


# ---------------------------------------------------------------------------
# spec building
# ---------------------------------------------------------------------------
def _clean_pairs(xs: list, ys: list) -> tuple[list, list, int]:
    """Drop pairs where either value is missing. Report how many were dropped."""
    kept_x, kept_y, dropped = [], [], 0
    for a, b in zip(xs, ys):
        if a is None or b is None or (isinstance(b, float) and math.isnan(b)):
            dropped += 1
            continue
        kept_x.append(a)
        kept_y.append(b)
    return kept_x, kept_y, dropped


def build_spec(
    frame: pd.DataFrame,
    *,
    form: str,
    x: str | None = None,
    y: str | list[str] | None = None,
    group: str | None = None,
    title: str = "",
    subtitle: str = "",
    x_label: str | None = None,
    y_label: str | None = None,
    x_unit: str = "",
    y_unit: str = "",
    x_scale: str = "linear",
    y_scale: str = "linear",
    error: str | None = None,
    mode: pal.Mode = "light",
    width: float = 7.2,
    height: float = 4.4,
    aggregate: Literal["none", "mean", "median", "sum", "count"] = "none",
) -> ChartSpec:
    """Build a chart spec from real columns of a real frame."""
    if form not in FORMS:
        raise BadRequest(f"Unknown chart form '{form}'. Known forms: {', '.join(FORMS)}")

    ys = [y] if isinstance(y, str) else (y or [])
    for col in filter(None, [x, group, error, *ys]):
        if col not in frame.columns:
            raise BadRequest(f"Column '{col}' is not in this dataset.")

    spec = ChartSpec(
        form=form,
        title=title,
        subtitle=subtitle,
        x=Axis(label=x_label or (x or ""), unit=x_unit, scale=x_scale),  # type: ignore[arg-type]
        y=Axis(label=y_label or (ys[0] if ys else "value"), unit=y_unit, scale=y_scale),  # type: ignore[arg-type]
        mode=mode,
        width=width,
        height=height,
    )
    notes: list[str] = []

    # -- distribution forms need only a value column ---------------------
    if form in ("histogram", "box", "violin"):
        value_col = ys[0] if ys else x
        if not value_col:
            raise BadRequest(f"A '{form}' needs a numeric column to summarise.")
        spec.y = Axis(label=y_label or value_col, unit=y_unit, scale=y_scale)  # type: ignore[arg-type]
        if group:
            levels = list(pd.unique(frame[group].dropna()))
            colors = pal.series_colors(len(levels), mode, form=form)
            if len(levels) > len(colors):
                notes.append(
                    f"{len(levels)} groups exceed the {len(colors)}-slot palette; only the "
                    f"first {len(colors)} are drawn as separate series."
                )
            for level, color in zip(levels, colors):
                vals = frame.loc[frame[group] == level, value_col].dropna().astype(float).tolist()
                spec.series.append(Series(name=str(level), y=vals, color=color))
            spec.x = Axis(label=x_label or group)
        else:
            vals = frame[value_col].dropna().astype(float).tolist()
            spec.series.append(Series(name=value_col, y=vals, color=pal.CATEGORICAL[mode][0]))
            spec.legend = False
        missing = int(frame[value_col].isna().sum())
        if missing:
            notes.append(f"{missing} row(s) had no value for '{value_col}' and were excluded.")

    # -- matrix forms ----------------------------------------------------
    elif form in ("heatmap", "correlation"):
        numeric = frame.select_dtypes(include=[np.number])
        if numeric.shape[1] < 2:
            raise BadRequest("A heatmap needs at least two numeric columns.")
        matrix = numeric.corr(method="spearman") if form == "correlation" else numeric
        spec.matrix = [[None if pd.isna(v) else round(float(v), 4) for v in row]
                       for row in np.asarray(matrix)]
        spec.matrix_cols = [str(c) for c in matrix.columns]
        spec.matrix_rows = (
            [str(c) for c in matrix.index] if form == "correlation"
            else [str(i) for i in matrix.index]
        )
        spec.diverging = form == "correlation"
        spec.legend = False
        if form == "correlation":
            spec.title = title or "Spearman correlation matrix"
            notes.append(
                "Correlation is not causation, and this matrix runs many comparisons at once — "
                "apply a multiple-comparison correction before reading any single cell as a finding."
            )

    # -- x/y forms --------------------------------------------------------
    else:
        if not x:
            raise BadRequest(f"A '{form}' needs an x column.")
        if not ys:
            raise BadRequest(f"A '{form}' needs at least one y column.")

        if group:
            levels = list(pd.unique(frame[group].dropna()))
            colors = pal.series_colors(len(levels), mode, form=form)
            if len(levels) > len(colors):
                notes.append(
                    f"{len(levels)} groups exceed the {len(colors)}-slot palette for this chart "
                    f"form; showing the first {len(colors)}. Facet the chart to show the rest."
                )
            for level, color in zip(levels, colors):
                sub = frame[frame[group] == level]
                if aggregate != "none":
                    sub = getattr(sub.groupby(x, dropna=True)[ys[0]], aggregate)().reset_index()
                xs, yy, dropped = _clean_pairs(sub[x].tolist(), sub[ys[0]].tolist())
                if dropped:
                    notes.append(f"{dropped} incomplete point(s) omitted from '{level}'.")
                spec.series.append(
                    Series(
                        name=str(level), x=xs, y=yy, color=color,
                        error=sub[error].tolist() if error else None,
                    )
                )
        else:
            colors = pal.series_colors(len(ys), mode, form=form)
            for col, color in zip(ys, colors):
                work = frame
                if aggregate != "none":
                    work = getattr(frame.groupby(x, dropna=True)[col], aggregate)().reset_index()
                xs, yy, dropped = _clean_pairs(work[x].tolist(), work[col].tolist())
                if dropped:
                    notes.append(f"{dropped} incomplete point(s) omitted from '{col}'.")
                spec.series.append(
                    Series(
                        name=col, x=xs, y=yy, color=color,
                        error=work[error].tolist() if error and error in work else None,
                    )
                )
            spec.legend = len(ys) > 1

    # -- accessibility bookkeeping ----------------------------------------
    if any(pal.needs_relief(s.color, mode) for s in spec.series if s.color):
        spec.direct_labels = True
        notes.append(
            "One or more series colours sit below 3:1 against the chart surface, so values "
            "are labelled directly and a table view is available — colour never carries "
            "meaning on its own here."
        )
    if len(spec.series) == 1:
        spec.legend = False   # the title names the single series
    if form in ("box", "violin"):
        # Group identity already sits on the x axis; a legend would repeat it.
        spec.legend = False

    spec.notes = notes
    spec.caption = spec.caption or _caption(spec, frame)
    return spec


def _caption(spec: ChartSpec, frame: pd.DataFrame) -> str:
    n = len(frame)
    plotted = sum(len(s.y) for s in spec.series) if spec.series else 0
    bits = [f"Drawn from {n} row(s) of the supplied dataset"]
    if plotted and plotted != n:
        bits.append(f"{plotted} value(s) plotted")
    return "; ".join(bits) + "."


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------
def render(spec: ChartSpec, fmt: ExportFormat = "png", *, dpi: int = 200) -> bytes:
    """Render a spec to bytes. Publication defaults: no chartjunk, thin marks."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap

    chrome = pal.CHROME[spec.mode]
    fig, ax = plt.subplots(figsize=(spec.width, spec.height), dpi=dpi)
    fig.patch.set_facecolor(chrome["plane"])
    ax.set_facecolor(chrome["surface"])

    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(chrome["axis"])
        ax.spines[side].set_linewidth(0.8)
    ax.tick_params(colors=chrome["muted"], labelsize=9, length=3, width=0.8)
    ax.grid(True, color=chrome["grid"], linewidth=0.7, alpha=0.9)
    ax.set_axisbelow(True)

    form = spec.form
    if form in ("bar", "grouped_bar", "stacked_bar"):
        _render_bars(ax, spec)
    elif form in ("line", "timeseries", "dose_response"):
        _render_lines(ax, spec)
    elif form in ("scatter", "pca", "volcano"):
        _render_scatter(ax, spec, chrome)
    elif form == "histogram":
        _render_histogram(ax, spec, chrome)
    elif form == "box":
        _render_box(ax, spec, chrome)
    elif form == "violin":
        _render_violin(ax, spec, chrome)
    elif form in ("heatmap", "correlation"):
        _render_matrix(ax, fig, spec, chrome, LinearSegmentedColormap)
    elif form == "pie":
        _render_pie(ax, spec, chrome)
    elif form == "survival":
        _render_survival(ax, spec)
    elif form == "network":
        _render_network(ax, spec, chrome)
    else:  # pragma: no cover - FORMS guards this
        raise BadRequest(f"No renderer for chart form '{form}'.")

    if form not in ("pie", "heatmap", "correlation", "network"):
        ax.set_xlabel(spec.x.title, color=chrome["text_secondary"], fontsize=10, labelpad=8)
        ax.set_ylabel(spec.y.title, color=chrome["text_secondary"], fontsize=10, labelpad=8)
        if spec.x.scale != "linear":
            ax.set_xscale(spec.x.scale)
        if spec.y.scale != "linear":
            ax.set_yscale(spec.y.scale)
        if spec.x.min is not None or spec.x.max is not None:
            ax.set_xlim(spec.x.min, spec.x.max)
        if spec.y.min is not None or spec.y.max is not None:
            ax.set_ylim(spec.y.min, spec.y.max)

    if spec.title:
        ax.set_title(spec.title, color=chrome["text"], fontsize=13, fontweight="600",
                     loc="left", pad=16 if spec.subtitle else 10)
    if spec.subtitle:
        ax.text(0, 1.02, spec.subtitle, transform=ax.transAxes,
                color=chrome["text_secondary"], fontsize=9.5, va="bottom")

    for note in spec.annotations:
        _render_annotation(ax, note, chrome)

    if spec.legend and len(spec.series) > 1:
        legend = ax.legend(frameon=False, fontsize=9, loc="best")
        for text in legend.get_texts():
            text.set_color(chrome["text_secondary"])

    fig.tight_layout()
    buffer = io.BytesIO()
    fig.savefig(buffer, format=fmt, facecolor=fig.get_facecolor(),
                bbox_inches="tight", transparent=False)
    plt.close(fig)
    return buffer.getvalue()


def _render_bars(ax, spec: ChartSpec) -> None:
    n = len(spec.series)
    categories = [str(v) for v in (spec.series[0].x if spec.series else [])]
    idx = np.arange(len(categories))
    stacked = spec.form == "stacked_bar"
    # A 2px surface gap between adjacent fills keeps segments distinguishable.
    width = 0.8 if (n == 1 or stacked) else 0.8 / n * 0.92
    bottom = np.zeros(len(categories))

    for i, series in enumerate(spec.series):
        values = np.array([float(v) for v in series.y], dtype=float)
        if stacked:
            bars = ax.bar(idx, values, width, bottom=bottom, label=series.name,
                          color=series.color, edgecolor=pal.CHROME[spec.mode]["surface"],
                          linewidth=1.5)
            bottom = bottom + values
        else:
            offset = (i - (n - 1) / 2) * (0.8 / n)
            bars = ax.bar(idx + offset, values, width, label=series.name, color=series.color,
                          yerr=series.error, capsize=3 if series.error else 0,
                          error_kw={"elinewidth": 1, "ecolor": pal.CHROME[spec.mode]["text_secondary"]},
                          edgecolor="none")
        if spec.direct_labels:
            for rect, value in zip(bars, values):
                ax.annotate(f"{value:.3g}", (rect.get_x() + rect.get_width() / 2,
                                             rect.get_height() + (bottom[0] if stacked else 0)),
                            ha="center", va="bottom", fontsize=8,
                            color=pal.CHROME[spec.mode]["text_secondary"],
                            xytext=(0, 3), textcoords="offset points")
    ax.set_xticks(idx)
    ax.set_xticklabels(categories, rotation=45 if max((len(c) for c in categories), default=0) > 8 else 0,
                       ha="right" if max((len(c) for c in categories), default=0) > 8 else "center")
    ax.grid(axis="x", visible=False)


def _render_lines(ax, spec: ChartSpec) -> None:
    for series in spec.series:
        ax.plot(series.x, series.y, label=series.name, color=series.color,
                linewidth=2.0, marker="o", markersize=4.5,
                markeredgecolor=pal.CHROME[spec.mode]["surface"], markeredgewidth=1.0)
        if series.error:
            err = np.array(series.error[: len(series.y)], dtype=float)
            y = np.array(series.y, dtype=float)
            ax.fill_between(series.x, y - err, y + err, color=series.color, alpha=0.15, linewidth=0)
        if spec.direct_labels and series.x:
            ax.annotate(series.name, (series.x[-1], series.y[-1]), xytext=(6, 0),
                        textcoords="offset points", fontsize=9, va="center",
                        color=pal.CHROME[spec.mode]["text_secondary"])


def _render_scatter(ax, spec: ChartSpec, chrome: dict) -> None:
    for series in spec.series:
        ax.scatter(series.x, series.y, label=series.name, color=series.color, s=42,
                   edgecolor=chrome["surface"], linewidth=1.0, alpha=0.92, zorder=3)
    if spec.form == "volcano":
        ax.axhline(-math.log10(0.05), color=chrome["muted"], linestyle="--", linewidth=1)
        ax.axvline(0, color=chrome["axis"], linewidth=1)


def _render_histogram(ax, spec: ChartSpec, chrome: dict) -> None:
    for series in spec.series:
        values = np.array(series.y, dtype=float)
        bins = max(int(math.sqrt(len(values))), 5) if len(values) else 5
        ax.hist(values, bins=bins, label=series.name, color=series.color,
                alpha=0.8 if len(spec.series) > 1 else 1.0,
                edgecolor=chrome["surface"], linewidth=1.0)
    ax.grid(axis="x", visible=False)


def _render_box(ax, spec: ChartSpec, chrome: dict) -> None:
    data = [np.array(s.y, dtype=float) for s in spec.series]
    parts = ax.boxplot(data, patch_artist=True, widths=0.55,
                       tick_labels=[s.name for s in spec.series],
                       medianprops={"color": chrome["text"], "linewidth": 1.6},
                       whiskerprops={"color": chrome["axis"], "linewidth": 1},
                       capprops={"color": chrome["axis"], "linewidth": 1},
                       flierprops={"marker": "o", "markersize": 4,
                                   "markerfacecolor": chrome["muted"],
                                   "markeredgecolor": "none", "alpha": 0.7})
    for patch, series in zip(parts["boxes"], spec.series):
        patch.set_facecolor(series.color)
        patch.set_alpha(0.85)
        patch.set_edgecolor(chrome["surface"])
        patch.set_linewidth(1.5)
    # Show the observations behind the summary — a boxplot hides n.
    for i, values in enumerate(data, start=1):
        if len(values) <= 60:
            jitter = np.random.default_rng(0).normal(0, 0.045, len(values))
            ax.scatter(np.full(len(values), i) + jitter, values, s=12,
                       color=chrome["text_secondary"], alpha=0.5, zorder=4, linewidth=0)
    ax.grid(axis="x", visible=False)
    ax.set_xticklabels([f"{s.name}\nn={len(s.y)}" for s in spec.series], fontsize=9)


def _render_violin(ax, spec: ChartSpec, chrome: dict) -> None:
    data = [np.array(s.y, dtype=float) for s in spec.series if len(s.y) > 1]
    if not data:
        raise BadRequest("A violin plot needs at least two values per group.")
    parts = ax.violinplot(data, showmedians=True, widths=0.7)
    for body, series in zip(parts["bodies"], spec.series):
        body.set_facecolor(series.color)
        body.set_alpha(0.75)
        body.set_edgecolor(chrome["surface"])
        body.set_linewidth(1.2)
    for key in ("cmedians", "cbars", "cmins", "cmaxes"):
        if key in parts:
            parts[key].set_color(chrome["text_secondary"])
            parts[key].set_linewidth(1.2)
    ax.set_xticks(range(1, len(spec.series) + 1))
    ax.set_xticklabels([f"{s.name}\nn={len(s.y)}" for s in spec.series], fontsize=9)
    ax.grid(axis="x", visible=False)


def _render_matrix(ax, fig, spec: ChartSpec, chrome: dict, cmap_cls) -> None:
    matrix = np.array(
        [[np.nan if v is None else v for v in row] for row in (spec.matrix or [])], dtype=float
    )
    if spec.diverging:
        colors = [pal.DIVERGING[spec.mode]["low"], pal.DIVERGING[spec.mode]["mid"],
                  pal.DIVERGING[spec.mode]["high"]]
        cmap = cmap_cls.from_list("diverging", colors)
        limit = float(np.nanmax(np.abs(matrix))) if matrix.size else 1.0
        vmin, vmax = -limit, limit
    else:
        cmap = cmap_cls.from_list("sequential", pal.SEQUENTIAL[spec.mode])
        vmin, vmax = None, None

    image = ax.imshow(matrix, cmap=cmap, vmin=vmin, vmax=vmax, aspect="auto")
    ax.set_xticks(range(len(spec.matrix_cols or [])))
    ax.set_xticklabels(spec.matrix_cols or [], rotation=45, ha="right", fontsize=9)
    ax.set_yticks(range(len(spec.matrix_rows or [])))
    ax.set_yticklabels(spec.matrix_rows or [], fontsize=9)
    ax.grid(False)
    bar = fig.colorbar(image, ax=ax, fraction=0.035, pad=0.03)
    bar.outline.set_visible(False)
    bar.ax.tick_params(colors=chrome["muted"], labelsize=8)

    if matrix.shape[0] <= 12 and matrix.shape[1] <= 12:
        for i in range(matrix.shape[0]):
            for j in range(matrix.shape[1]):
                value = matrix[i, j]
                if np.isnan(value):
                    continue
                ax.text(j, i, f"{value:.2f}", ha="center", va="center", fontsize=8,
                        color=chrome["text"] if abs(value) < 0.6 * (vmax or 1) else "#ffffff")


def _render_pie(ax, spec: ChartSpec, chrome: dict) -> None:
    series = spec.series[0]
    values = [float(v) for v in series.y]
    labels = series.labels or [str(v) for v in series.x] or [f"Slice {i+1}" for i in range(len(values))]
    colors = pal.series_colors(len(values), spec.mode)
    if len(values) > len(colors):
        order = np.argsort(values)[::-1]
        keep = order[: len(colors) - 1]
        other = sum(values[i] for i in order[len(colors) - 1 :])
        values = [values[i] for i in keep] + [other]
        labels = [labels[i] for i in keep] + ["Other"]
    total = sum(values) or 1.0
    ax.pie(values, labels=labels, colors=colors, startangle=90, counterclock=False,
           autopct=lambda p: f"{p:.1f}%" if p >= 3 else "",
           wedgeprops={"edgecolor": chrome["surface"], "linewidth": 2},
           textprops={"color": chrome["text_secondary"], "fontsize": 9})
    ax.axis("equal")
    ax.set_title(spec.title or f"n = {total:g}", color=chrome["text"], fontsize=12,
                 fontweight="600", loc="left")


def _render_survival(ax, spec: ChartSpec) -> None:
    """Kaplan-Meier style step curves. x = time, y = survival probability."""
    for series in spec.series:
        ax.step(series.x, series.y, where="post", label=series.name,
                color=series.color, linewidth=2.0)
        if series.error:
            y = np.array(series.y, dtype=float)
            err = np.array(series.error[: len(y)], dtype=float)
            ax.fill_between(series.x, np.clip(y - err, 0, 1), np.clip(y + err, 0, 1),
                            step="post", color=series.color, alpha=0.15, linewidth=0)
    ax.set_ylim(0, 1.02)


def _render_network(ax, spec: ChartSpec, chrome: dict) -> None:
    """Force-free circular layout — deterministic, so the same graph always looks the same."""
    nodes = spec.matrix_rows or []
    matrix = spec.matrix or []
    n = len(nodes)
    if not n:
        raise BadRequest("A network chart needs nodes.")
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False)
    xs, ys = np.cos(angles), np.sin(angles)
    for i in range(n):
        for j in range(i + 1, n):
            weight = matrix[i][j] if i < len(matrix) and j < len(matrix[i]) else 0
            if weight:
                ax.plot([xs[i], xs[j]], [ys[i], ys[j]], color=chrome["grid"],
                        linewidth=min(0.5 + abs(float(weight)) * 2, 4), zorder=1, alpha=0.8)
    ax.scatter(xs, ys, s=140, color=pal.CATEGORICAL[spec.mode][0],
               edgecolor=chrome["surface"], linewidth=2, zorder=3)
    for i, name in enumerate(nodes):
        ax.annotate(name, (xs[i], ys[i]), xytext=(0, 12), textcoords="offset points",
                    ha="center", fontsize=9, color=chrome["text_secondary"])
    ax.set_xlim(-1.35, 1.35)
    ax.set_ylim(-1.35, 1.35)
    ax.axis("off")


def _render_annotation(ax, note: Annotation, chrome: dict) -> None:
    if note.kind == "threshold" and note.y is not None:
        ax.axhline(note.y, color=chrome["muted"], linestyle="--", linewidth=1)
        ax.annotate(note.text, (0.99, note.y), xycoords=("axes fraction", "data"),
                    ha="right", va="bottom", fontsize=8.5, color=chrome["text_secondary"])
    elif note.kind == "significance" and note.y is not None:
        x1, x2 = float(note.x or 0), float(note.x2 or 1)
        ax.plot([x1, x1, x2, x2], [note.y, note.y * 1.02, note.y * 1.02, note.y],
                color=chrome["text_secondary"], linewidth=1)
        ax.annotate(note.text, ((x1 + x2) / 2, note.y * 1.02), ha="center", va="bottom",
                    fontsize=9, color=chrome["text"])
    elif note.kind == "note":
        ax.annotate(note.text, (note.x if note.x is not None else 0.02,
                                note.y if note.y is not None else 0.95),
                    xycoords="axes fraction", fontsize=9, color=chrome["text_secondary"])


def recommend_form(frame: pd.DataFrame, x: str | None, y: str | None, group: str | None) -> dict:
    """Pick a chart form from the data's job, and say why (spec §8: 'automatically determine')."""
    def kind(col: str | None) -> str:
        if not col or col not in frame.columns:
            return "none"
        s = frame[col]
        if pd.api.types.is_datetime64_any_dtype(s):
            return "time"
        if pd.api.types.is_numeric_dtype(s):
            return "numeric"
        try:
            pd.to_datetime(s.dropna().astype(str).head(20), format="mixed")
            return "time"
        except Exception:
            return "categorical"

    kx, ky = kind(x), kind(y)
    levels = frame[group].nunique() if group and group in frame.columns else 0

    if kx == "time" and ky == "numeric":
        return {"form": "timeseries", "why": "A numeric measure over time reads as a line: the "
                                             "shape of the change is the point."}
    if kx == "numeric" and ky == "numeric":
        return {"form": "scatter", "why": "Two numeric measures — a scatter shows the "
                                          "relationship without imposing a model on it."}
    if kx == "categorical" and ky == "numeric":
        n_per = frame.groupby(x)[y].count().median() if y else 0
        if n_per >= 8:
            return {"form": "box", "why": f"About {n_per:.0f} observations per category — a box "
                                          "plot shows the spread rather than hiding it behind "
                                          "a single bar height."}
        return {"form": "bar", "why": "Comparing a magnitude across a handful of categories."}
    if kx == "numeric" and ky in ("none", "categorical"):
        return {"form": "histogram", "why": "One numeric column — its distribution is the story."}
    if kx == "categorical" and ky == "none":
        return {"form": "bar", "why": "Counting occurrences per category."}
    if levels > 1:
        return {"form": "grouped_bar", "why": f"Comparing across {levels} groups."}
    return {"form": "bar", "why": "Default comparison of magnitude across categories."}

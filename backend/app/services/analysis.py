"""Statistics and dataset inspection (spec §9).

Two rules shape this module:

* Values are never invented.  Missing cells are reported, counted and located;
  they are never imputed unless the user explicitly asks, and when they are,
  the report says so and says how.
* A test is never run silently.  Every result carries the assumptions the test
  makes, whether they were checked, and what the check found — because "p =
  0.03" from a t-test on non-normal, unequal-variance data is not a finding.

Everything here is deterministic and computed from the actual data, so results
are reproducible and the emitted code re-derives exactly these numbers.
"""
from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd
from scipy import stats

from ..core.errors import BadRequest

MISSING_MARKERS = ("", "na", "n/a", "nan", "null", "none", "-", "--", "?", "missing")


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------
def load_frame(data: bytes, filename: str, *, sheet: str | None = None) -> pd.DataFrame:
    lower = filename.lower()
    try:
        if lower.endswith((".xlsx", ".xls", ".xlsm")):
            return pd.read_excel(io.BytesIO(data), sheet_name=sheet or 0)
        if lower.endswith(".json"):
            return pd.json_normalize(json.loads(data.decode("utf-8")))
        sep = "\t" if lower.endswith(".tsv") else None   # None => sniff
        return pd.read_csv(io.BytesIO(data), sep=sep, engine="python")
    except Exception as exc:  # noqa: BLE001
        raise BadRequest(f"Could not read '{filename}' as a dataset: {exc}") from exc


def frame_from_records(records: list[dict]) -> pd.DataFrame:
    if not records:
        raise BadRequest("No rows were supplied.")
    return pd.DataFrame.from_records(records)


# ---------------------------------------------------------------------------
# profiling
# ---------------------------------------------------------------------------
def profile(frame: pd.DataFrame, *, max_columns: int = 200) -> dict[str, Any]:
    """Describe a dataset honestly: shape, types, missingness, outliers."""
    if frame.empty:
        return {"rows": 0, "columns": [], "note": "The dataset contains no rows."}

    columns: list[dict[str, Any]] = []
    for name in list(frame.columns)[:max_columns]:
        col = frame[name]
        missing = int(col.isna().sum())
        entry: dict[str, Any] = {
            "name": str(name),
            "dtype": str(col.dtype),
            "missing": missing,
            "missing_pct": round(100.0 * missing / len(frame), 2),
            "unique": int(col.nunique(dropna=True)),
        }
        if pd.api.types.is_numeric_dtype(col):
            clean = col.dropna().astype(float)
            entry["kind"] = "numeric"
            if len(clean):
                q1, q3 = float(clean.quantile(0.25)), float(clean.quantile(0.75))
                iqr = q3 - q1
                lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
                outliers = clean[(clean < lo) | (clean > hi)]
                entry.update(
                    {
                        "mean": round(float(clean.mean()), 6),
                        "median": round(float(clean.median()), 6),
                        "sd": round(float(clean.std(ddof=1)), 6) if len(clean) > 1 else None,
                        "sem": round(float(clean.sem(ddof=1)), 6) if len(clean) > 1 else None,
                        "min": round(float(clean.min()), 6),
                        "max": round(float(clean.max()), 6),
                        "q1": round(q1, 6),
                        "q3": round(q3, 6),
                        "iqr": round(iqr, 6),
                        "outlier_count": int(len(outliers)),
                        "outlier_rows": [int(i) for i in outliers.index[:25]],
                        "outlier_rule": "Tukey fence: outside Q1-1.5*IQR to Q3+1.5*IQR",
                    }
                )
                if len(clean) >= 3:
                    entry["skew"] = round(float(clean.skew()), 4)
                    entry["normality"] = normality(clean)
        else:
            entry["kind"] = "categorical"
            counts = col.dropna().astype(str).value_counts().head(12)
            entry["top_values"] = [{"value": k, "count": int(v)} for k, v in counts.items()]
            if entry["unique"] == len(frame):
                entry["note"] = "Every value is unique — this looks like an identifier."
        columns.append(entry)

    duplicated = int(frame.duplicated().sum())
    total_cells = frame.shape[0] * frame.shape[1]
    notes: list[str] = []
    if duplicated:
        notes.append(f"{duplicated} fully duplicated row(s) found.")
    heavy = [c["name"] for c in columns if c["missing_pct"] > 20]
    if heavy:
        notes.append(
            "High missingness (>20%) in: " + ", ".join(heavy)
            + ". Nothing has been filled in; decide how to handle these before analysing."
        )
    return {
        "rows": int(frame.shape[0]),
        "column_count": int(frame.shape[1]),
        "columns": columns,
        "duplicate_rows": duplicated,
        "missing_cells": int(frame.isna().sum().sum()),
        "missing_pct": round(100.0 * frame.isna().sum().sum() / total_cells, 2) if total_cells else 0.0,
        "notes": notes,
    }


def normality(series: pd.Series) -> dict[str, Any]:
    """Shapiro-Wilk where valid, D'Agostino otherwise. Reported, never assumed."""
    clean = pd.Series(series).dropna().astype(float)
    n = len(clean)
    if n < 3:
        return {"test": None, "note": f"Only {n} value(s) — normality cannot be assessed."}
    if float(clean.std(ddof=0)) == 0.0:
        # A constant column has no distribution to test; saying "normal" would be absurd.
        return {
            "test": None,
            "note": f"Every value is {clean.iloc[0]:g} — a constant column, so normality "
                    f"does not apply and this column carries no variance to analyse.",
        }
    if n <= 5000:
        stat, p = stats.shapiro(clean)
        test = "Shapiro-Wilk"
    else:
        stat, p = stats.normaltest(clean)
        test = "D'Agostino-Pearson"
    return {
        "test": test,
        "statistic": round(float(stat), 5),
        "p_value": float(p),
        "normal_at_0.05": bool(p > 0.05),
        "note": (
            "Consistent with a normal distribution at alpha=0.05."
            if p > 0.05
            else "Departs from normality at alpha=0.05 — prefer a rank-based test, or justify the parametric one."
        ),
    }


# ---------------------------------------------------------------------------
# statistical tests
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class TestResult:
    name: str
    statistic: float | None
    p_value: float | None
    effect: dict[str, Any] = field(default_factory=dict)
    groups: dict[str, Any] = field(default_factory=dict)
    assumptions: list[dict[str, Any]] = field(default_factory=list)
    interpretation: str = ""
    warnings: list[str] = field(default_factory=list)
    code: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "test": self.name,
            "statistic": self.statistic,
            "p_value": self.p_value,
            "effect": self.effect,
            "groups": self.groups,
            "assumptions": self.assumptions,
            "interpretation": self.interpretation,
            "warnings": self.warnings,
            "reproducible_code": self.code,
        }


def _describe_group(values: pd.Series) -> dict[str, Any]:
    clean = values.dropna().astype(float)
    return {
        "n": int(len(clean)),
        "mean": round(float(clean.mean()), 6) if len(clean) else None,
        "median": round(float(clean.median()), 6) if len(clean) else None,
        "sd": round(float(clean.std(ddof=1)), 6) if len(clean) > 1 else None,
        "sem": round(float(clean.sem(ddof=1)), 6) if len(clean) > 1 else None,
    }


def _p_words(p: float | None, alpha: float = 0.05) -> str:
    if p is None:
        return "no p-value could be computed"
    if p < 0.001:
        return "p < 0.001"
    return f"p = {p:.4g}" + ("" if p < alpha else f" (above alpha={alpha})")


def compare_groups(
    frame: pd.DataFrame,
    value_column: str,
    group_column: str,
    *,
    paired: bool = False,
    parametric: Literal["auto", "yes", "no"] = "auto",
    alpha: float = 0.05,
) -> TestResult:
    """Two- or k-group comparison, choosing the test from checked assumptions."""
    for col in (value_column, group_column):
        if col not in frame.columns:
            raise BadRequest(f"Column '{col}' is not in this dataset.")

    work = frame[[value_column, group_column]].dropna()
    if work.empty:
        raise BadRequest(
            f"After dropping missing values, no rows remain for "
            f"'{value_column}' by '{group_column}'. Nothing was substituted in their place."
        )
    levels = list(pd.unique(work[group_column]))
    samples = [work.loc[work[group_column] == lvl, value_column].astype(float) for lvl in levels]
    groups = {str(lvl): _describe_group(s) for lvl, s in zip(levels, samples)}

    warnings: list[str] = []
    dropped = len(frame) - len(work)
    if dropped:
        warnings.append(f"{dropped} row(s) with missing values were excluded, not imputed.")
    small = [str(lvl) for lvl, s in zip(levels, samples) if len(s) < 3]
    if small:
        warnings.append(f"Group(s) {', '.join(small)} have fewer than 3 observations.")
    if len(levels) < 2:
        raise BadRequest(f"'{group_column}' has only one level; there is nothing to compare.")

    assumptions: list[dict[str, Any]] = []
    normal_all = True
    for lvl, sample in zip(levels, samples):
        res = normality(sample)
        assumptions.append({"assumption": f"Normality of '{lvl}'", **res})
        if res.get("test") and not res.get("normal_at_0.05", True):
            normal_all = False

    equal_var = True
    if all(len(s) > 1 for s in samples):
        lev_stat, lev_p = stats.levene(*samples, center="median")
        equal_var = bool(lev_p > 0.05)
        assumptions.append(
            {
                "assumption": "Equal variances (Levene, median-centred)",
                "test": "Levene",
                "statistic": round(float(lev_stat), 5),
                "p_value": float(lev_p),
                "satisfied": equal_var,
                "note": "Variances are comparable."
                if equal_var
                else "Variances differ — using a variance-robust form of the test.",
            }
        )

    use_parametric = normal_all if parametric == "auto" else (parametric == "yes")
    if parametric == "yes" and not normal_all:
        warnings.append(
            "A parametric test was requested although at least one group departs from "
            "normality. The p-value should be read with that in mind."
        )

    # -- two groups ----------------------------------------------------
    if len(levels) == 2:
        a, b = samples
        if paired:
            if len(a) != len(b):
                raise BadRequest(
                    f"A paired test needs equal group sizes; got {len(a)} and {len(b)}."
                )
            if use_parametric:
                stat, p = stats.ttest_rel(a, b)
                name = "Paired t-test"
                code = f"stats.ttest_rel(a, b)  # a={levels[0]!r}, b={levels[1]!r}"
            else:
                stat, p = stats.wilcoxon(a, b)
                name = "Wilcoxon signed-rank test"
                code = "stats.wilcoxon(a, b)"
        elif use_parametric:
            stat, p = stats.ttest_ind(a, b, equal_var=equal_var)
            name = "Welch's t-test" if not equal_var else "Student's t-test"
            code = f"stats.ttest_ind(a, b, equal_var={equal_var})"
        else:
            stat, p = stats.mannwhitneyu(a, b, alternative="two-sided")
            name = "Mann-Whitney U test"
            code = "stats.mannwhitneyu(a, b, alternative='two-sided')"

        effect: dict[str, Any] = {}
        if len(a) > 1 and len(b) > 1:
            pooled = np.sqrt(((len(a) - 1) * a.var(ddof=1) + (len(b) - 1) * b.var(ddof=1))
                             / (len(a) + len(b) - 2))
            if pooled > 0:
                d = float((a.mean() - b.mean()) / pooled)
                effect["cohens_d"] = round(d, 4)
                effect["cohens_d_reading"] = (
                    "negligible" if abs(d) < 0.2 else "small" if abs(d) < 0.5
                    else "medium" if abs(d) < 0.8 else "large"
                )
            # Rank-biserial: the effect size that matches a rank-based test.
            u = float(stats.mannwhitneyu(a, b, alternative="two-sided").statistic)
            effect["rank_biserial"] = round(1 - (2 * u) / (len(a) * len(b)), 4)
            diff = float(a.mean() - b.mean())
            se = float(np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b)))
            if se > 0:
                crit = stats.t.ppf(1 - alpha / 2, df=max(len(a) + len(b) - 2, 1))
                effect["mean_difference"] = round(diff, 6)
                effect[f"ci_{int((1-alpha)*100)}"] = [
                    round(diff - crit * se, 6), round(diff + crit * se, 6)
                ]

        significant = p is not None and p < alpha
        interpretation = (
            f"{name}: {_p_words(float(p), alpha)}. "
            + (
                f"The difference between '{levels[0]}' and '{levels[1]}' is unlikely under the "
                f"null hypothesis at alpha={alpha}."
                if significant
                else f"This does not establish a difference between '{levels[0]}' and "
                     f"'{levels[1]}'; it also does not establish that they are the same."
            )
        )
        return TestResult(
            name=name, statistic=round(float(stat), 6), p_value=float(p), effect=effect,
            groups=groups, assumptions=assumptions, interpretation=interpretation,
            warnings=warnings, code=code,
        )

    # -- k groups ------------------------------------------------------
    if use_parametric and equal_var:
        stat, p = stats.f_oneway(*samples)
        name = "One-way ANOVA"
        code = "stats.f_oneway(*groups)"
    elif use_parametric:
        stat, p = stats.alexandergovern(*samples).statistic, stats.alexandergovern(*samples).pvalue
        name = "Alexander-Govern test (unequal variances)"
        code = "stats.alexandergovern(*groups)"
    else:
        stat, p = stats.kruskal(*samples)
        name = "Kruskal-Wallis H test"
        code = "stats.kruskal(*groups)"

    grand = np.concatenate([s.to_numpy() for s in samples])
    ss_between = sum(len(s) * (s.mean() - grand.mean()) ** 2 for s in samples)
    ss_total = float(((grand - grand.mean()) ** 2).sum())
    effect = {"eta_squared": round(float(ss_between / ss_total), 4)} if ss_total else {}

    warnings.append(
        "An omnibus test says only that the groups are not all alike. Follow up with "
        "pairwise comparisons and a multiple-comparison correction to say which differ."
    )
    return TestResult(
        name=name, statistic=round(float(stat), 6), p_value=float(p), effect=effect,
        groups=groups, assumptions=assumptions,
        interpretation=f"{name} across {len(levels)} groups: {_p_words(float(p), alpha)}.",
        warnings=warnings, code=code,
    )


def correlate(
    frame: pd.DataFrame, x: str, y: str, *, method: Literal["auto", "pearson", "spearman"] = "auto"
) -> TestResult:
    for col in (x, y):
        if col not in frame.columns:
            raise BadRequest(f"Column '{col}' is not in this dataset.")
    work = frame[[x, y]].dropna().astype(float)
    if len(work) < 3:
        raise BadRequest(f"Only {len(work)} complete pair(s) — too few to correlate.")

    assumptions = [
        {"assumption": f"Normality of '{x}'", **normality(work[x])},
        {"assumption": f"Normality of '{y}'", **normality(work[y])},
    ]
    both_normal = all(a.get("normal_at_0.05", False) for a in assumptions if a.get("test"))
    chosen = method if method != "auto" else ("pearson" if both_normal else "spearman")

    if chosen == "pearson":
        r, p = stats.pearsonr(work[x], work[y])
        name, code = "Pearson correlation", f"stats.pearsonr(df['{x}'], df['{y}'])"
    else:
        r, p = stats.spearmanr(work[x], work[y])
        name, code = "Spearman rank correlation", f"stats.spearmanr(df['{x}'], df['{y}'])"

    strength = (
        "negligible" if abs(r) < 0.1 else "weak" if abs(r) < 0.3
        else "moderate" if abs(r) < 0.5 else "strong" if abs(r) < 0.7 else "very strong"
    )
    return TestResult(
        name=name, statistic=round(float(r), 5), p_value=float(p),
        effect={"r": round(float(r), 5), "r_squared": round(float(r) ** 2, 5), "strength": strength,
                "n": int(len(work))},
        assumptions=assumptions,
        interpretation=(
            f"{name} between '{x}' and '{y}': r = {r:.3f} ({strength}, {_p_words(float(p))}), "
            f"n = {len(work)}. Correlation describes co-movement only — it is not evidence "
            f"that one causes the other, and a lurking third variable is always possible."
        ),
        warnings=(
            [] if len(work) >= 30
            else [f"n = {len(work)}: correlation estimates are unstable in small samples."]
        ),
        code=code,
    )


def regress(frame: pd.DataFrame, x: str, y: str) -> TestResult:
    """Ordinary least squares with residual diagnostics."""
    for col in (x, y):
        if col not in frame.columns:
            raise BadRequest(f"Column '{col}' is not in this dataset.")
    work = frame[[x, y]].dropna().astype(float)
    if len(work) < 3:
        raise BadRequest(f"Only {len(work)} complete pair(s) — too few to fit a line.")

    fit = stats.linregress(work[x], work[y])
    predicted = fit.intercept + fit.slope * work[x]
    residuals = work[y] - predicted
    resid_normal = normality(residuals)
    # Breusch-Pagan-flavoured check: do squared residuals trend with the fitted values?
    het_r, het_p = stats.spearmanr(predicted, residuals.abs())

    return TestResult(
        name="Ordinary least squares regression",
        statistic=round(float(fit.slope), 6),
        p_value=float(fit.pvalue),
        effect={
            "slope": round(float(fit.slope), 6),
            "intercept": round(float(fit.intercept), 6),
            "r_squared": round(float(fit.rvalue) ** 2, 5),
            "std_err": round(float(fit.stderr), 6),
            "n": int(len(work)),
            "equation": f"{y} = {fit.intercept:.4g} + {fit.slope:.4g} * {x}",
        },
        assumptions=[
            {"assumption": "Normality of residuals", **resid_normal},
            {
                "assumption": "Homoscedasticity (|residual| vs fitted, Spearman)",
                "test": "Spearman rank",
                "statistic": round(float(het_r), 5),
                "p_value": float(het_p),
                "satisfied": bool(het_p > 0.05),
                "note": "Residual spread looks constant."
                if het_p > 0.05
                else "Residual spread changes with the fitted value; standard errors and the "
                     "p-value are unreliable as reported.",
            },
            {
                "assumption": "Linearity and independence",
                "test": None,
                "note": "Not tested automatically. Inspect the residual plot, and consider "
                        "whether observations are truly independent (repeated measures, "
                        "time series and clustered designs are not).",
            },
        ],
        interpretation=(
            f"Each 1-unit increase in '{x}' is associated with a change of {fit.slope:.4g} in "
            f"'{y}' (R² = {fit.rvalue ** 2:.3f}, {_p_words(float(fit.pvalue))}, n = {len(work)}). "
            f"This is an association in these data, not a demonstrated causal effect."
        ),
        warnings=[] if len(work) >= 20 else [f"n = {len(work)} is small for a stable fit."],
        code=f"stats.linregress(df['{x}'], df['{y}'])",
    )


def correlation_matrix(
    frame: pd.DataFrame, columns: list[str] | None = None, *, method: str = "spearman"
) -> dict[str, Any]:
    numeric = frame[columns] if columns else frame.select_dtypes(include=[np.number])
    numeric = numeric.dropna(axis=1, how="all")
    if numeric.shape[1] < 2:
        raise BadRequest("At least two numeric columns are needed for a correlation matrix.")
    matrix = numeric.corr(method=method)
    pairs = []
    cols = list(matrix.columns)
    for i, a in enumerate(cols):
        for b in cols[i + 1 :]:
            sub = numeric[[a, b]].dropna()
            if len(sub) < 3:
                continue
            r, p = (stats.spearmanr if method == "spearman" else stats.pearsonr)(sub[a], sub[b])
            pairs.append({"x": a, "y": b, "r": round(float(r), 4), "p_value": float(p), "n": len(sub)})
    pairs.sort(key=lambda row: abs(row["r"]), reverse=True)
    return {
        "method": method,
        "columns": cols,
        "matrix": [[round(float(v), 4) for v in row] for row in matrix.to_numpy()],
        "pairs": pairs,
        "note": (
            f"{len(pairs)} pairwise comparisons were computed. With this many tests some small "
            "p-values are expected by chance; apply a correction (e.g. Benjamini-Hochberg) "
            "before treating any single pair as a finding."
        ),
    }


def describe(frame: pd.DataFrame, columns: list[str] | None = None) -> dict[str, Any]:
    numeric = frame[columns] if columns else frame.select_dtypes(include=[np.number])
    out = {}
    for name in numeric.columns:
        out[str(name)] = _describe_group(numeric[name]) | {
            "min": float(numeric[name].min()) if numeric[name].notna().any() else None,
            "max": float(numeric[name].max()) if numeric[name].notna().any() else None,
            "missing": int(numeric[name].isna().sum()),
        }
    return out


def reproducible_script(dataset_name: str, steps: list[str]) -> str:
    """Emit a runnable script that reproduces the analysis just performed."""
    body = "\n".join(f"{s}" for s in steps)
    return (
        "# Reproduces the analysis performed in the workspace.\n"
        "# Missing values are dropped pairwise and never imputed.\n"
        "import pandas as pd\n"
        "from scipy import stats\n\n"
        f"df = pd.read_csv({dataset_name!r})\n\n"
        f"{body}\n"
    )

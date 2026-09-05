"""Statistics (spec §9): never fabricate, always state the assumptions."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.core.errors import BadRequest
from app.services import analysis


@pytest.fixture()
def frame():
    rng = np.random.default_rng(11)
    return pd.DataFrame(
        {
            "arm": ["control"] * 20 + ["treated"] * 20,
            "value": [*rng.normal(10, 2, 20), *rng.normal(14, 2, 20)],
            "dose": rng.uniform(0, 10, 40),
            "constant": [7.0] * 40,
        }
    )


def test_profile_counts_missing_without_filling_it(frame):
    frame.loc[3, "value"] = np.nan
    profile = analysis.profile(frame)
    value = next(c for c in profile["columns"] if c["name"] == "value")
    assert value["missing"] == 1
    assert profile["missing_cells"] == 1
    # the frame itself is untouched — nothing was imputed
    assert pd.isna(frame.loc[3, "value"])


def test_outliers_are_located_not_just_counted(frame):
    frame.loc[0, "value"] = 500.0
    value = next(c for c in analysis.profile(frame)["columns"] if c["name"] == "value")
    assert value["outlier_count"] >= 1
    assert 0 in value["outlier_rows"]
    assert "IQR" in value["outlier_rule"]


def test_constant_column_is_not_called_normal(frame):
    result = analysis.normality(frame["constant"])
    assert result["test"] is None
    assert "constant" in result["note"]


def test_group_comparison_reports_its_assumptions(frame):
    result = analysis.compare_groups(frame, "value", "arm")
    dimensions = [a["assumption"] for a in result.assumptions]
    assert any("Normality" in d for d in dimensions)
    assert any("Equal variances" in d for d in dimensions)
    assert all(a.get("test") or a.get("note") for a in result.assumptions)


def test_non_normal_data_switches_to_a_rank_test(frame):
    frame.loc[0, "value"] = 900.0     # drags the control group off normality
    result = analysis.compare_groups(frame, "value", "arm")
    assert "Mann-Whitney" in result.name


def test_missing_rows_are_excluded_and_said_so(frame):
    frame.loc[[1, 2, 3], "value"] = np.nan
    result = analysis.compare_groups(frame, "value", "arm")
    assert any("not imputed" in w for w in result.warnings)
    assert result.groups["control"]["n"] == 17


def test_reproducible_code_is_emitted(frame):
    assert analysis.compare_groups(frame, "value", "arm").code
    assert analysis.correlate(frame, "dose", "value").code


def test_correlation_states_it_is_not_causation(frame):
    result = analysis.correlate(frame, "dose", "value")
    assert "not evidence" in result.interpretation or "causal" in result.interpretation


def test_omnibus_test_warns_that_it_is_not_pairwise(frame):
    frame["arm"] = ["a"] * 13 + ["b"] * 13 + ["c"] * 14
    result = analysis.compare_groups(frame, "value", "arm")
    assert any("pairwise" in w for w in result.warnings)


def test_regression_checks_residuals(frame):
    result = analysis.regress(frame, "dose", "value")
    dimensions = [a["assumption"] for a in result.assumptions]
    assert any("residual" in d.lower() for d in dimensions)
    assert any("Linearity" in d for d in dimensions)
    assert "not a demonstrated causal effect" in result.interpretation


def test_matrix_warns_about_multiple_comparisons(frame):
    result = analysis.correlation_matrix(frame, ["value", "dose"])
    assert "correction" in result["note"]


def test_missing_column_is_a_clear_error(frame):
    with pytest.raises(BadRequest, match="not in this dataset"):
        analysis.compare_groups(frame, "nope", "arm")


def test_single_level_group_is_refused(frame):
    single = frame[frame["arm"] == "control"]
    with pytest.raises(BadRequest, match="nothing to compare"):
        analysis.compare_groups(single, "value", "arm")


def test_all_missing_is_refused_not_invented(frame):
    frame["value"] = np.nan
    with pytest.raises(BadRequest, match="Nothing was substituted"):
        analysis.compare_groups(frame, "value", "arm")

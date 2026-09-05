"""Charting (spec §8): built from real values, with the palette rules honoured."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.core.errors import BadRequest
from app.services import charts, palette


@pytest.fixture()
def frame():
    rng = np.random.default_rng(3)
    return pd.DataFrame(
        {
            "arm": ["control"] * 12 + ["treated"] * 12,
            "value": [*rng.normal(10, 1, 12), *rng.normal(13, 1, 12)],
            "dose": rng.uniform(0, 10, 24),
        }
    )


def test_values_come_from_the_data(frame):
    spec = charts.build_spec(frame, form="bar", x="arm", y="value", aggregate="mean")
    means = frame.groupby("arm")["value"].mean()
    for category, plotted in zip(spec.series[0].x, spec.series[0].y):
        assert plotted == pytest.approx(means[category])


def test_missing_points_are_dropped_and_reported(frame):
    frame.loc[0, "value"] = np.nan
    spec = charts.build_spec(frame, form="scatter", x="dose", y="value")
    assert len(spec.series[0].y) == 23
    assert any("omitted" in note for note in spec.notes)


def test_categorical_colours_follow_fixed_slot_order(frame):
    spec = charts.build_spec(frame, form="box", x="arm", y="value", group="arm")
    assert [s.color for s in spec.series] == palette.CATEGORICAL["light"][:2]


def test_scatter_forms_cap_the_series_count():
    """All-pairs forms cannot use all eight slots and stay CVD-safe."""
    frame = pd.DataFrame(
        {"g": [f"g{i}" for i in range(8)] * 3, "x": range(24), "y": range(24)}
    )
    spec = charts.build_spec(frame, form="scatter", x="x", y="y", group="g")
    assert len(spec.series) == palette.ALL_PAIRS_CAP
    assert any("exceed" in note for note in spec.notes)


def test_low_contrast_slots_trigger_the_relief_rule():
    frame = pd.DataFrame({"g": ["a", "b", "c"] * 4, "x": range(12), "y": range(12)})
    spec = charts.build_spec(frame, form="bar", x="x", y="y", group="g")
    assert spec.direct_labels
    assert spec.table_view


def test_single_series_needs_no_legend(frame):
    spec = charts.build_spec(frame, form="line", x="dose", y="value")
    assert spec.legend is False


def test_distribution_forms_put_identity_on_the_axis(frame):
    spec = charts.build_spec(frame, form="box", x="arm", y="value", group="arm")
    assert spec.legend is False


def test_form_recommendation_explains_itself(frame):
    result = charts.recommend_form(frame, "arm", "value", None)
    assert result["form"] == "box"
    assert result["why"]


def test_correlation_matrix_is_diverging_with_a_caveat(frame):
    spec = charts.build_spec(frame, form="correlation")
    assert spec.diverging
    assert any("causation" in note for note in spec.notes)


@pytest.mark.parametrize("fmt", ["png", "svg", "pdf"])
def test_render_produces_a_real_file(frame, fmt):
    spec = charts.build_spec(frame, form="box", x="arm", y="value", group="arm")
    payload = charts.render(spec, fmt)
    assert len(payload) > 1000
    if fmt == "png":
        assert payload[:8] == b"\x89PNG\r\n\x1a\n"
    if fmt == "pdf":
        assert payload[:4] == b"%PDF"


def test_unknown_form_is_refused(frame):
    with pytest.raises(BadRequest, match="Unknown chart form"):
        charts.build_spec(frame, form="pyramid", x="arm", y="value")


def test_missing_column_is_refused(frame):
    with pytest.raises(BadRequest, match="not in this dataset"):
        charts.build_spec(frame, form="bar", x="nope", y="value")


def test_sequential_ordinal_ramp_stays_readable():
    steps = palette.sequential_steps(4, "light", ordinal=True)
    assert steps[0] not in palette.SEQUENTIAL["light"][:3]

"""Chart palette — one system, light and dark, validated for colour-vision deficiency.

Categorical hues are assigned in **fixed slot order and never cycled**: an
eighth series is the last one that gets its own colour; beyond that, series fold
into "Other" or the chart is faceted.  The ordering itself is the CVD-safety
mechanism (worst adjacent pair ΔE 9.1 light / 8.4 dark), so it must not be
re-shuffled for aesthetics.

Scatter/bubble forms compare *all* pairs rather than adjacent ones, so they cap
at the first three slots, which clear the all-pairs floors in both modes.
"""
from __future__ import annotations

from typing import Literal

Mode = Literal["light", "dark"]

CATEGORICAL: dict[Mode, list[str]] = {
    "light": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
              "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
    "dark":  ["#3987e5", "#d95926", "#199e70", "#c98500",
              "#d55181", "#008300", "#9085e9", "#e66767"],
}

#: Forms that put every pair on screen at once cannot use all eight slots.
ALL_PAIRS_CAP = 3
ALL_PAIRS_FORMS = frozenset({"scatter", "bubble", "pca", "volcano", "network"})

SEQUENTIAL: dict[Mode, list[str]] = {
    "light": ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7",
              "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"],
    "dark":  ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7",
              "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"],
}

#: Diverging = two hues + a *neutral* midpoint. Never a hue in the middle.
DIVERGING: dict[Mode, dict[str, str]] = {
    "light": {"low": "#2a78d6", "mid": "#f0efec", "high": "#d03b3b"},
    "dark":  {"low": "#3987e5", "mid": "#383835", "high": "#e34948"},
}

#: Reserved for state. Never reused as a series colour, always with icon + label.
STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}

CHROME: dict[Mode, dict[str, str]] = {
    "light": {
        "surface": "#fcfcfb", "plane": "#f9f9f7", "text": "#0b0b0b",
        "text_secondary": "#52514e", "muted": "#898781",
        "grid": "#e1e0d9", "axis": "#c3c2b7",
    },
    "dark": {
        "surface": "#1a1a19", "plane": "#0d0d0d", "text": "#ffffff",
        "text_secondary": "#c3c2b7", "muted": "#898781",
        "grid": "#2c2c2a", "axis": "#383835",
    },
}

#: Slots that sit below 3:1 on the light surface — these require the relief rule
#: (visible direct labels or a table view), never colour alone.
LOW_CONTRAST_LIGHT = frozenset({"#1baf7a", "#eda100", "#e87ba4"})


def series_colors(count: int, mode: Mode = "light", *, form: str = "bar") -> list[str]:
    """Fixed-order slots for ``count`` series. Never generates a new hue."""
    slots = CATEGORICAL[mode]
    cap = ALL_PAIRS_CAP if form in ALL_PAIRS_FORMS else len(slots)
    return [slots[i] for i in range(min(count, cap, len(slots)))]


def series_cap(form: str) -> int:
    return ALL_PAIRS_CAP if form in ALL_PAIRS_FORMS else len(CATEGORICAL["light"])


def needs_relief(color: str, mode: Mode) -> bool:
    """True when this slot needs direct labels or a table view to stay readable."""
    return mode == "light" and color.lower() in LOW_CONTRAST_LIGHT


def sequential_steps(n: int, mode: Mode = "light", *, ordinal: bool = False) -> list[str]:
    """``n`` steps of the single sequential hue, light→dark.

    Ordinal ramps (discrete ordered marks) must clear 2:1 against the surface,
    so on light they start no lighter than step 250.
    """
    ramp = SEQUENTIAL[mode]
    if ordinal:
        ramp = ramp[3:] if mode == "light" else ramp[:-2]
    if n <= 1:
        return [ramp[len(ramp) // 2]]
    step = (len(ramp) - 1) / (n - 1)
    return [ramp[round(i * step)] for i in range(n)]

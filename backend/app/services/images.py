"""Scientific image analysis (§5) and comparison (§6).

The hard rule for scientific figures: **observation and interpretation are kept
apart.** A blot has bands at certain positions and intensities — that is what is
visible. What those bands mean depends on loading controls, antibody
specificity, replicate count and exposure, most of which a single image cannot
establish. The prompt and the output shape both enforce that separation, and the
"cannot be concluded" list is a required field, not a nicety.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Literal

from ..config import settings
from ..core.errors import BadRequest, ProviderUnavailable
from ..core.registry import registry
from ..providers.llm.base import ImageBlock, LlmMessage, LlmRequest

ImageKind = Literal[
    "auto", "figure", "microscopy", "western_blot", "gel", "flow_cytometry",
    "histology", "chart", "graph", "screenshot", "diagram", "handwriting",
    "table", "results", "textbook_page", "photograph",
]

MAX_IMAGES_PER_CALL = 12
SUPPORTED_MEDIA = ("image/png", "image/jpeg", "image/gif", "image/webp")

KIND_GUIDANCE: dict[str, str] = {
    "western_blot": (
        "For a Western blot, describe lane order, band positions relative to any ladder, "
        "relative intensity and band shape. Then state explicitly what cannot be concluded "
        "from the image alone: whether loading is equal without a visible loading control, "
        "antibody specificity, quantitation without densitometry across replicates, and "
        "whether the image shows cropped or spliced lanes."
    ),
    "gel": (
        "For an electrophoresis gel, report lane contents, band sizes against the ladder, "
        "smearing and background. Note that band presence is not proof of identity without "
        "sequencing or a specific probe."
    ),
    "flow_cytometry": (
        "For flow cytometry, describe axes and their scales (linear/log), gate placement, "
        "population positions and quoted percentages. Say whether the gating strategy, "
        "compensation and controls (FMO, isotype, unstained) are visible; without them the "
        "percentages cannot be validated."
    ),
    "microscopy": (
        "For microscopy, describe what structures are visible, staining/channels, and the "
        "scale bar if present. If there is no scale bar, say that size cannot be judged. "
        "Note magnification claims cannot be verified from the image alone."
    ),
    "histology": (
        "For histology, describe tissue architecture, cell morphology and staining pattern. "
        "Distinguish clearly between describing morphology and offering a diagnosis — a "
        "single field is not a diagnosis."
    ),
    "chart": (
        "For a chart, read axis labels, units, scale type and tick values, then report the "
        "values you can actually read off. Where a value falls between gridlines, say it is "
        "approximate and give the bracket rather than a precise number. Flag truncated axes, "
        "dual axes, missing error bars and missing n."
    ),
    "handwriting": (
        "Transcribe the handwriting as literally as you can. Mark any word you are unsure of "
        "as [illegible] or [word?] rather than guessing at it."
    ),
    "table": (
        "Transcribe the table faithfully, preserving row and column structure. Mark cells you "
        "cannot read as [unreadable]. Do not fill in a value you cannot see."
    ),
}

ANALYSIS_SCHEMA = {
    "detected_kind": "string — what kind of image this appears to be",
    "observations": ["what is literally visible, with no interpretation"],
    "text_in_image": ["verbatim text, labels, axis titles, legends you can read"],
    "measurements": [
        {"what": "string", "value": "string", "certainty": "read directly | approximate | not readable"}
    ],
    "interpretation": ["what these observations could mean, flagged as interpretation"],
    "cannot_conclude": ["what this image does NOT establish, and why"],
    "quality_issues": ["cropping, compression, missing controls, missing scale bar, ..."],
    "relation_to_question": "string or null — how this bears on the research question",
}

SYSTEM = """You analyse scientific and general images for a researcher.

The single most important rule: separate OBSERVATION from INTERPRETATION.
- "observations" contains only what is visibly present in the pixels.
- "interpretation" contains what it might mean, and is always hedged.
- "cannot_conclude" is mandatory and must be substantive.

Other rules:
- Read numbers off the image only when they are legible. If a value falls between
  gridlines, give a range and mark it "approximate". Never state a precise figure
  you cannot actually read.
- If the image is too low-resolution, cropped, or ambiguous to support a claim,
  say so instead of hedging your way into an answer.
- Do not identify individuals in photographs.
- You are not making a clinical diagnosis. For medical images, describe features
  and state plainly that diagnosis requires the full clinical context and a
  qualified clinician."""

COMPARISON_SCHEMA = {
    "per_image": [{"image": "IMG1", "summary": "string", "key_features": ["string"]}],
    "common_features": ["string"],
    "differences": [
        {"aspect": "string", "image_a": "IMG1", "image_b": "IMG2", "difference": "string",
         "confidence": "clear | probable | uncertain"}
    ],
    "likely_relationship": "string — e.g. same experiment different timepoints, replicate, control vs treated",
    "suggested_ordering": ["IMG1", "IMG2"],
    "ordering_rationale": "string",
    "cannot_conclude": ["string"],
}

COMPARISON_SYSTEM = """You compare scientific images for a researcher.

- Refer to images by their labels (IMG1, IMG2, ...).
- Differences must be visible differences, each marked clear / probable / uncertain.
- Apparent intensity or colour differences may be artefacts of exposure, gain,
  compression or display. Say so when that is a live possibility.
- Never claim two images come from the same experiment, sample or replicate unless
  something visible in them supports it.
- "cannot_conclude" is mandatory."""


@dataclass(slots=True)
class ImageInput:
    label: str
    data: bytes
    media_type: str = "image/png"
    filename: str = ""
    kind: ImageKind = "auto"
    caption: str | None = None

    def block(self) -> ImageBlock:
        return ImageBlock(
            data_b64=base64.b64encode(self.data).decode("ascii"),
            media_type=self.media_type,
            label=f"{self.label}"
            + (f" — {self.filename}" if self.filename else "")
            + (f" — caption: {self.caption}" if self.caption else ""),
        )


def _vision_provider():
    for provider in registry.resolve("llm", settings.llm_provider):
        if getattr(provider, "supports_vision", False):
            return provider
    raise ProviderUnavailable(
        "Image analysis needs a vision-capable model, and none is configured. "
        "Set ANTHROPIC_API_KEY or OPENAI_API_KEY. Everything else in the workspace "
        "— search, papers, statistics, charts — works without it.",
        detail={"capability": "llm+vision"},
    )


def _validate(images: list[ImageInput]) -> None:
    if not images:
        raise BadRequest("No images were supplied.")
    if len(images) > MAX_IMAGES_PER_CALL:
        raise BadRequest(
            f"{len(images)} images in one request exceeds the {MAX_IMAGES_PER_CALL}-image "
            f"limit per analysis. A project can hold many more — analyse them in batches, "
            f"and the workspace keeps the results together."
        )
    for image in images:
        if image.media_type not in SUPPORTED_MEDIA:
            raise BadRequest(
                f"'{image.filename or image.label}' is {image.media_type}; supported types "
                f"are {', '.join(SUPPORTED_MEDIA)}."
            )


async def analyse(
    image: ImageInput,
    *,
    question: str | None = None,
    kind: ImageKind = "auto",
    context: str = "",
) -> dict[str, Any]:
    """Analyse one image, keeping observation separate from interpretation."""
    _validate([image])
    provider = _vision_provider()
    guidance = KIND_GUIDANCE.get(kind if kind != "auto" else image.kind, "")

    prompt_parts = ["Analyse this image."]
    if guidance:
        prompt_parts.append(guidance)
    if question:
        prompt_parts.append(f"The researcher's question: {question}")
    if context:
        prompt_parts.append(f"Project context (for relevance only, not for facts):\n{context[:4000]}")

    payload = await provider.complete_json(
        LlmRequest(
            messages=[
                LlmMessage(role="user", content="\n\n".join(prompt_parts), images=[image.block()])
            ],
            system=SYSTEM,
            intent="image_analysis",
            json_schema=ANALYSIS_SCHEMA,
            max_tokens=4000,
            temperature=0.1,
        )
    )
    payload["label"] = image.label
    payload["filename"] = image.filename
    payload.setdefault("cannot_conclude", [])
    if not payload["cannot_conclude"]:
        payload["cannot_conclude"] = [
            "The model returned no limits for this image; treat every reading below as "
            "provisional until checked against the original."
        ]
    payload["disclaimer"] = (
        "Observations describe the pixels. Interpretations are the model's reading of them, "
        "not a finding — check them against the original data."
    )
    return payload


async def compare(
    images: list[ImageInput],
    *,
    question: str | None = None,
    context: str = "",
) -> dict[str, Any]:
    """Compare several images, holding all of them in one context (spec §6)."""
    _validate(images)
    if len(images) < 2:
        raise BadRequest("Comparison needs at least two images.")
    provider = _vision_provider()

    instruction = question or (
        "Compare these images: what is shared, what differs, and how do they most "
        "plausibly relate to one another?"
    )
    if context:
        instruction += f"\n\nProject context:\n{context[:4000]}"

    payload = await provider.complete_json(
        LlmRequest(
            messages=[
                LlmMessage(
                    role="user",
                    content=instruction,
                    images=[image.block() for image in images],
                )
            ],
            system=COMPARISON_SYSTEM,
            intent="image_comparison",
            json_schema=COMPARISON_SCHEMA,
            max_tokens=5000,
            temperature=0.1,
        )
    )
    known = {image.label for image in images}
    payload["differences"] = [
        d for d in (payload.get("differences") or [])
        if isinstance(d, dict) and {d.get("image_a"), d.get("image_b")} <= known
    ]
    payload["suggested_ordering"] = [
        label for label in (payload.get("suggested_ordering") or []) if label in known
    ]
    payload["images"] = [
        {"label": i.label, "filename": i.filename, "kind": i.kind} for i in images
    ]
    payload.setdefault("cannot_conclude", [])
    payload["disclaimer"] = (
        "Apparent differences in brightness, contrast or colour between images can come from "
        "acquisition or compression rather than from the samples."
    )
    return payload

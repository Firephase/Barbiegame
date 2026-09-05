"""Diagram authoring (spec §7).

Diagrams are emitted as **Mermaid source**, which means they are text: the user
can read them, the model can revise them surgically, they diff cleanly in a
project's history, and they render natively in the browser without a plotting
service.

The module validates structure before returning anything — an unparseable
diagram is a failure to report, not something to hand over and hope.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from ..core.errors import BadRequest, ProviderUnavailable
from ..core.registry import registry
from ..config import settings
from ..providers.llm.base import LlmMessage, LlmRequest

DiagramKind = Literal[
    "pathway", "workflow", "mechanism", "process", "flowchart", "concept_map",
    "molecular_workflow", "framework", "timeline", "decision_tree",
    "architecture", "knowledge_graph", "sequence", "state",
]

#: Which Mermaid dialect suits each requested kind.
_DIALECT: dict[str, str] = {
    "pathway": "flowchart LR", "workflow": "flowchart TD", "mechanism": "flowchart LR",
    "process": "flowchart TD", "flowchart": "flowchart TD", "concept_map": "flowchart LR",
    "molecular_workflow": "flowchart TD", "framework": "flowchart TD",
    "timeline": "timeline", "decision_tree": "flowchart TD",
    "architecture": "flowchart TB", "knowledge_graph": "flowchart LR",
    "sequence": "sequenceDiagram", "state": "stateDiagram-v2",
}

_VALID_STARTS = (
    "flowchart", "graph", "sequenceDiagram", "stateDiagram", "stateDiagram-v2",
    "timeline", "classDiagram", "erDiagram", "journey", "gantt", "mindmap",
    "quadrantChart", "gitGraph", "pie",
)

_FENCE = re.compile(r"```(?:mermaid)?\s*(.*?)```", re.DOTALL)

SYSTEM = """You are a scientific illustrator who writes Mermaid diagrams.

Rules:
- Output ONLY Mermaid source. No prose, no code fence, no explanation.
- Use the dialect the user names on the first line.
- Node ids are short and alphanumeric (A, B, step1). Labels go in brackets.
- Label every edge that carries meaning (activates, inhibits, yields, requires).
- Keep labels short enough to read at presentation size.
- Represent only what the user's material supports. If a step is uncertain or
  disputed, label it as such (e.g. "-.->|proposed| X") rather than drawing it as
  established fact.
- Never invent a mechanism, gene, or step that was not given to you or is not
  standard textbook knowledge in the field named."""


@dataclass
class Diagram:
    id: str
    kind: str
    title: str
    source: str                       # Mermaid text
    dialect: str = "flowchart TD"
    node_count: int = 0
    edge_count: int = 0
    notes: list[str] = field(default_factory=list)
    revision: int = 1
    history: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "title": self.title, "source": self.source,
            "dialect": self.dialect, "node_count": self.node_count,
            "edge_count": self.edge_count, "notes": self.notes, "revision": self.revision,
            "renderer": "mermaid",
        }


def clean_source(raw: str) -> str:
    """Strip fences and stray prose; keep from the first dialect keyword on."""
    text = raw.strip()
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith(_VALID_STARTS):
            return "\n".join(lines[i:]).strip()
    return text


def validate(source: str) -> tuple[bool, list[str], int, int]:
    """Structural check. Returns ``(ok, problems, nodes, edges)``."""
    problems: list[str] = []
    text = source.strip()
    if not text:
        return False, ["The diagram is empty."], 0, 0
    first = text.splitlines()[0].strip()
    if not first.startswith(_VALID_STARTS):
        problems.append(
            f"First line is '{first[:40]}', which is not a Mermaid diagram declaration."
        )

    edges = len(re.findall(r"(-->|---|-\.->|==>|-\.-|\|>|->>|-->>)", text))
    node_ids = set(re.findall(r"(?:^|[\s\[(])([A-Za-z_][A-Za-z0-9_]*)\s*[\[({]", text))
    node_ids |= set(re.findall(r"(?:-->|---|-\.->|==>)\s*\|?[^|]*\|?\s*([A-Za-z_][A-Za-z0-9_]*)", text))
    nodes = len(node_ids)

    if first.startswith(("flowchart", "graph")) and edges == 0:
        problems.append("A flowchart with no edges is a list, not a diagram.")
    if text.count("[") != text.count("]"):
        problems.append("Unbalanced square brackets.")
    if text.count("(") != text.count(")"):
        problems.append("Unbalanced parentheses.")
    if len(text) > 20000:
        problems.append("Diagram source is very large; consider splitting it.")
    return not problems, problems, nodes, edges


async def generate(
    description: str,
    *,
    kind: DiagramKind = "flowchart",
    title: str = "",
    context: str = "",
    diagram_id: str | None = None,
) -> Diagram:
    """Author a diagram from a natural-language description."""
    from ..core.provenance import new_id

    provider = registry.require("llm", settings.llm_provider)
    dialect = _DIALECT.get(kind, "flowchart TD")

    prompt = f"Dialect: {dialect}\n\nDiagram to draw:\n{description.strip()}"
    if context:
        prompt += (
            "\n\nBase the diagram on this material. Do not add steps it does not "
            f"support:\n---\n{context[:12000]}\n---"
        )

    try:
        result = await provider.complete(
            LlmRequest(
                messages=[LlmMessage(role="user", content=prompt)],
                system=SYSTEM,
                intent="diagram",
                max_tokens=2500,
                temperature=0.15,
            )
        )
    except ProviderUnavailable:
        raise
    source = clean_source(result.text)
    ok, problems, nodes, edges = validate(source)
    if not ok:
        # One repair attempt: hand the model its own errors rather than shipping
        # a diagram we already know is broken.
        retry = await provider.complete(
            LlmRequest(
                messages=[
                    LlmMessage(role="user", content=prompt),
                    LlmMessage(role="assistant", content=source),
                    LlmMessage(
                        role="user",
                        content="That diagram has problems: "
                        + "; ".join(problems)
                        + ". Return corrected Mermaid source only.",
                    ),
                ],
                system=SYSTEM,
                intent="diagram",
                max_tokens=2500,
                temperature=0.0,
            )
        )
        source = clean_source(retry.text)
        ok, problems, nodes, edges = validate(source)
        if not ok:
            raise BadRequest(
                "The diagram could not be generated as valid Mermaid: " + "; ".join(problems),
                detail={"source": source[:1500]},
            )

    return Diagram(
        id=diagram_id or new_id("dgm"),
        kind=kind,
        title=title or description[:70],
        source=source,
        dialect=dialect,
        node_count=nodes,
        edge_count=edges,
        notes=(
            ["Generated from your description without supporting sources."]
            if not context
            else ["Generated from the material in this project."]
        ),
    )


async def revise(diagram: Diagram, instruction: str, *, context: str = "") -> Diagram:
    """Apply a natural-language edit ('add this step', 'make it simpler')."""
    provider = registry.require("llm", settings.llm_provider)
    prompt = (
        f"Here is an existing Mermaid diagram:\n\n{diagram.source}\n\n"
        f"Change requested: {instruction.strip()}\n\n"
        "Return the complete revised diagram as Mermaid source only. Preserve every "
        "part the instruction does not ask you to change."
    )
    if context:
        prompt += f"\n\nSupporting material:\n---\n{context[:8000]}\n---"

    result = await provider.complete(
        LlmRequest(
            messages=[LlmMessage(role="user", content=prompt)],
            system=SYSTEM,
            intent="diagram",
            max_tokens=2500,
            temperature=0.1,
        )
    )
    source = clean_source(result.text)
    ok, problems, nodes, edges = validate(source)
    if not ok:
        raise BadRequest(
            "The revision produced invalid Mermaid, so the original diagram is unchanged: "
            + "; ".join(problems),
            detail={"attempted": source[:1200]},
        )

    return Diagram(
        id=diagram.id,
        kind=diagram.kind,
        title=diagram.title,
        source=source,
        dialect=diagram.dialect,
        node_count=nodes,
        edge_count=edges,
        notes=diagram.notes,
        revision=diagram.revision + 1,
        history=[*diagram.history, diagram.source],
    )


PRESENTATION_HINT = (
    "Make it suitable for a scientific presentation: at most 9 nodes, short labels, "
    "one clear left-to-right or top-down flow, no crossing edges, and no abbreviation "
    "that is not defined on the slide."
)

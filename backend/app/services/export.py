"""Export (spec §17): PDF, DOCX, Markdown, TXT, CSV, Excel, images, citation
files and slides.

Every exported format keeps the citations and the source links, and every one
carries the epistemic labels — a report that drops "AI inference" on its way
into a Word document has laundered the uncertainty out of the research.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Any, Literal

from ..core.errors import BadRequest
from ..core.provenance import Answer, Claim, Epistemic, Source
from .citations import STYLES, bibliography, format_citation, in_text

Format = Literal["md", "txt", "pdf", "docx", "csv", "xlsx", "bibtex", "ris", "json", "pptx"]

FORMATS: tuple[str, ...] = ("md", "txt", "pdf", "docx", "csv", "xlsx", "bibtex", "ris", "json", "pptx")

MEDIA_TYPES = {
    "md": "text/markdown",
    "txt": "text/plain",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "bibtex": "application/x-bibtex",
    "ris": "application/x-research-info-systems",
    "json": "application/json",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

_STATUS_MARK = {
    Epistemic.VERIFIED: "Verified",
    Epistemic.INTERPRETATION: "Interpretation",
    Epistemic.UNCERTAIN: "Uncertain",
    Epistemic.AI_INFERENCE: "AI inference — not evidence-backed",
}

DISCLAIMER = (
    "Statements below are labelled by how they were established. "
    "'Verified' means a retrieved source states it and the wording was checked against "
    "that source. 'Interpretation' means a source supports it but the reading is the "
    "assistant's. 'Uncertain' means sources are thin or disagree. "
    "'AI inference' means no retrieved source supports it — treat those as prompts for "
    "further checking, not as findings."
)


def _claim_lines(answer: Answer, style: str) -> list[tuple[Claim, str, str]]:
    """``(claim, marker, label)`` triples with resolved in-text citations."""
    numbering = {s.id: i for i, s in enumerate(answer.sources, start=1)}
    rows = []
    for claim in answer.claims:
        markers = []
        for citation in claim.citations:
            source = answer.source_by_id(citation.source_id)
            if source:
                markers.append(in_text(source, style, index=numbering.get(source.id)))
        rows.append((claim, " ".join(dict.fromkeys(markers)), _STATUS_MARK[claim.status]))
    return rows


# ---------------------------------------------------------------------------
# text formats
# ---------------------------------------------------------------------------
def to_markdown(answer: Answer, *, style: str = "apa", include_trace: bool = True) -> str:
    out: list[str] = [f"# {answer.question}", ""]
    out.append(f"*{answer.mode.replace('_', ' ').title()} · "
               f"{answer.created_at:%d %B %Y} · {len(answer.sources)} source(s)*")
    out.append("")
    if answer.warnings:
        out.append("> **Read this first**")
        for warning in answer.warnings:
            out.append(f"> - {warning}")
        out.append("")
    if answer.summary:
        out += ["## Summary", "", answer.summary, ""]

    if answer.claims:
        out += ["## Findings", "", f"*{DISCLAIMER}*", ""]
        for claim, marker, label in _claim_lines(answer, style):
            out.append(f"- **[{label}]** {claim.text} {marker}".rstrip())
            for citation in claim.citations:
                source = answer.source_by_id(citation.source_id)
                if source and citation.quote:
                    locator = f", {citation.locator}" if citation.locator else ""
                    out.append(f"  > “{citation.quote.strip()}” — {source.title}{locator}")
            if claim.verification_note:
                out.append(f"  *{claim.verification_note}*")
        out.append("")

    if answer.disagreements:
        out += ["## Where sources disagree", ""]
        for disagreement in answer.disagreements:
            out.append(f"### {disagreement.topic}")
            for position in disagreement.positions:
                titles = ", ".join(
                    (answer.source_by_id(sid).title if answer.source_by_id(sid) else sid)
                    for sid in position.source_ids
                )
                out.append(f"- **{position.stance}** — {titles}")
                if position.note:
                    out.append(f"  {position.note}")
            if disagreement.assessment:
                out.append(f"\n{disagreement.assessment}")
            out.append("")

    if answer.open_questions:
        out += ["## Open questions", ""] + [f"- {q}" for q in answer.open_questions] + [""]

    if answer.sources:
        out += ["## Sources", ""]
        for i, source in enumerate(answer.sources, start=1):
            out.append(f"{i}. {format_citation(source, style)}")
            if source.quality:
                out.append(f"   *Appraisal: {source.quality.summary}*")
            if source.url:
                out.append(f"   <{source.url}>")
        out.append("")

    if include_trace:
        trace = answer.trace
        out += ["## How this conclusion was reached", ""]
        if trace.queries_issued:
            out.append(f"**Searches run:** {'; '.join(trace.queries_issued)}")
        if trace.providers_used:
            out.append(f"**Providers used:** {', '.join(trace.providers_used)}")
        for entry in trace.providers_unavailable:
            out.append(f"**Unavailable:** {entry.get('provider')} — {entry.get('reason')}")
        out.append(f"**Sources considered:** {trace.sources_considered}; "
                   f"selected: {len(trace.sources_selected)}")
        if trace.assumptions:
            out += ["", "**Assumptions:**"] + [f"- {a}" for a in trace.assumptions]
        if trace.limitations:
            out += ["", "**Limitations:**"] + [f"- {x}" for x in trace.limitations]
        if trace.steps:
            out += ["", "**Steps:**"]
            for step in trace.steps:
                out.append(f"- `{step.stage}` {step.detail}")
        out.append("")

    out.append("---")
    out.append(
        f"*Generated by the research workspace on {datetime.utcnow():%Y-%m-%d %H:%M} UTC. "
        f"Confidence breakdown: "
        + ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in answer.confidence_breakdown.items())
        + ".*"
    )
    return "\n".join(out)


def to_text(answer: Answer, *, style: str = "apa") -> str:
    import re

    md = to_markdown(answer, style=style)
    text = re.sub(r"^#{1,6}\s*", "", md, flags=re.M)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", text)
    return re.sub(r"^> ?", "", text, flags=re.M)


def to_json(answer: Answer) -> str:
    return json.dumps(answer.model_dump(mode="json"), indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# citation files
# ---------------------------------------------------------------------------
def to_bibtex(sources: list[Source]) -> str:
    return bibliography(sources, "bibtex")


_RIS_TYPES = {
    "journal_article": "JOUR", "preprint": "JOUR", "book": "BOOK", "news": "NEWS",
    "web_page": "ELEC", "government": "RPRT", "institutional": "RPRT",
    "documentation": "ELEC", "dataset": "DATA", "video": "VIDEO",
    "uploaded_document": "GEN", "image": "FIGURE", "note": "GEN", "unknown": "GEN",
}


def to_ris(sources: list[Source]) -> str:
    """RIS — what Zotero, Mendeley and EndNote import."""
    chunks = []
    for source in sources:
        lines = [f"TY  - {_RIS_TYPES.get(source.kind.value, 'GEN')}", f"TI  - {source.title}"]
        for author in source.authors:
            lines.append(
                f"AU  - {author.family}, {author.given}" if author.family and author.given
                else f"AU  - {author.name}"
            )
        if source.container_title:
            lines.append(f"JO  - {source.container_title}")
        if source.published:
            lines.append(f"PY  - {source.published.year}")
            lines.append(f"DA  - {source.published:%Y/%m/%d}")
        for tag, value in (
            ("VL", source.volume), ("IS", source.issue), ("SP", source.pages),
            ("PB", source.publisher), ("DO", source.doi), ("UR", source.url),
            ("AB", (source.abstract or "").replace("\n", " ")[:2000]),
            ("LA", source.language),
        ):
            if value:
                lines.append(f"{tag}  - {value}")
        if source.kind.value == "preprint":
            lines.append("N1  - Preprint, not peer reviewed")
        lines.append("ER  - ")
        chunks.append("\n".join(lines))
    return "\n\n".join(chunks)


# ---------------------------------------------------------------------------
# tabular
# ---------------------------------------------------------------------------
_SOURCE_COLUMNS = [
    "n", "title", "authors", "year", "venue", "kind", "peer_reviewed", "doi", "url",
    "cited_by", "quality_tier", "full_text_retrieved", "appraisal", "caveats", "citation",
]


def _source_row(i: int, source: Source, style: str) -> list[Any]:
    return [
        i,
        source.title,
        "; ".join(a.name for a in source.authors),
        source.year or "",
        source.container_title or source.site_name or "",
        source.kind.value,
        "" if source.is_peer_reviewed is None else source.is_peer_reviewed,
        source.doi or "",
        source.url or "",
        source.cited_by_count if source.cited_by_count is not None else "",
        source.quality.tier if source.quality else "",
        source.full_text_retrieved,
        source.quality.summary if source.quality else "",
        "; ".join(source.quality.caveats) if source.quality else "",
        format_citation(source, style),
    ]


def sources_to_csv(sources: list[Source], *, style: str = "apa") -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_SOURCE_COLUMNS)
    for i, source in enumerate(sources, start=1):
        writer.writerow(_source_row(i, source, style))
    return buffer.getvalue()


def to_xlsx(answer: Answer, *, style: str = "apa") -> bytes:
    """Workbook with findings, sources and the reasoning trace on separate sheets."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    book = Workbook()
    header_font = Font(bold=True)

    findings = book.active
    findings.title = "Findings"
    findings.append(["#", "Statement", "Status", "Support score", "Cited sources", "Quote", "Note"])
    for i, (claim, marker, label) in enumerate(_claim_lines(answer, style), start=1):
        titles = "; ".join(
            (answer.source_by_id(c.source_id).title if answer.source_by_id(c.source_id) else c.source_id)
            for c in claim.citations
        )
        quote = " | ".join(filter(None, (c.quote for c in claim.citations)))
        findings.append([i, claim.text, label, claim.support_score or "", titles, quote,
                         claim.verification_note or ""])

    sheet = book.create_sheet("Sources")
    sheet.append(_SOURCE_COLUMNS)
    for i, source in enumerate(answer.sources, start=1):
        sheet.append(_source_row(i, source, style))

    trace_sheet = book.create_sheet("How it was reached")
    trace_sheet.append(["Field", "Value"])
    trace = answer.trace
    rows: list[tuple[str, str]] = [
        ("Question", answer.question),
        ("Mode", answer.mode),
        ("Generated", f"{answer.created_at:%Y-%m-%d %H:%M UTC}"),
        ("Searches run", "; ".join(trace.queries_issued)),
        ("Providers used", ", ".join(trace.providers_used)),
        ("Providers unavailable", "; ".join(
            f"{e.get('provider')}: {e.get('reason')}" for e in trace.providers_unavailable
        )),
        ("Sources considered", str(trace.sources_considered)),
        ("Sources selected", str(len(trace.sources_selected))),
    ]
    rows += [("Assumption", a) for a in trace.assumptions]
    rows += [("Limitation", x) for x in trace.limitations]
    rows += [("Warning", w) for w in answer.warnings]
    rows += [(f"Step: {s.stage}", s.detail) for s in trace.steps]
    for row in rows:
        trace_sheet.append(list(row))

    for ws in book.worksheets:
        for cell in ws[1]:
            cell.font = header_font
        for column in ws.columns:
            width = max((len(str(c.value or "")) for c in column[:60]), default=10)
            ws.column_dimensions[column[0].column_letter].width = min(max(width + 2, 12), 70)
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = Alignment(wrap_text=True, vertical="top")

    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# documents
# ---------------------------------------------------------------------------
def to_docx(answer: Answer, *, style: str = "apa", include_trace: bool = True) -> bytes:
    import docx
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    document = docx.Document()
    document.core_properties.title = answer.question
    document.core_properties.comments = "Generated by the research workspace."

    document.add_heading(answer.question, level=0)
    meta = document.add_paragraph()
    meta.add_run(
        f"{answer.mode.replace('_', ' ').title()} · {answer.created_at:%d %B %Y} · "
        f"{len(answer.sources)} source(s)"
    ).italic = True

    if answer.warnings:
        document.add_heading("Read this first", level=1)
        for warning in answer.warnings:
            para = document.add_paragraph(warning, style="List Bullet")
            para.runs[0].font.color.rgb = RGBColor(0xD0, 0x3B, 0x3B)

    if answer.summary:
        document.add_heading("Summary", level=1)
        document.add_paragraph(answer.summary)

    if answer.claims:
        document.add_heading("Findings", level=1)
        note = document.add_paragraph(DISCLAIMER)
        note.runs[0].italic = True
        note.runs[0].font.size = Pt(9)
        for claim, marker, label in _claim_lines(answer, style):
            para = document.add_paragraph(style="List Bullet")
            tag = para.add_run(f"[{label}] ")
            tag.bold = True
            tag.font.color.rgb = (
                RGBColor(0x0C, 0xA3, 0x0C) if claim.status == Epistemic.VERIFIED
                else RGBColor(0xEB, 0x68, 0x34) if claim.status == Epistemic.INTERPRETATION
                else RGBColor(0xFA, 0xB2, 0x19) if claim.status == Epistemic.UNCERTAIN
                else RGBColor(0x89, 0x87, 0x81)
            )
            para.add_run(claim.text + (f" {marker}" if marker else ""))
            for citation in claim.citations:
                if citation.quote:
                    quote = document.add_paragraph(f"“{citation.quote.strip()}”", style="Quote")
                    quote.runs[0].font.size = Pt(9)

    if answer.disagreements:
        document.add_heading("Where sources disagree", level=1)
        for disagreement in answer.disagreements:
            document.add_heading(disagreement.topic, level=2)
            for position in disagreement.positions:
                titles = ", ".join(
                    (answer.source_by_id(sid).title if answer.source_by_id(sid) else sid)
                    for sid in position.source_ids
                )
                para = document.add_paragraph(style="List Bullet")
                para.add_run(position.stance).bold = True
                para.add_run(f" — {titles}")
            if disagreement.assessment:
                document.add_paragraph(disagreement.assessment)

    if answer.open_questions:
        document.add_heading("Open questions", level=1)
        for question in answer.open_questions:
            document.add_paragraph(question, style="List Bullet")

    if answer.sources:
        document.add_heading("Sources", level=1)
        for i, source in enumerate(answer.sources, start=1):
            para = document.add_paragraph(f"{i}. {format_citation(source, style)}")
            para.paragraph_format.left_indent = Pt(18)
            para.paragraph_format.first_line_indent = Pt(-18)
            if source.quality:
                appraisal = document.add_paragraph(f"Appraisal: {source.quality.summary}")
                appraisal.runs[0].italic = True
                appraisal.runs[0].font.size = Pt(9)
                appraisal.paragraph_format.left_indent = Pt(18)

    if include_trace:
        document.add_page_break()
        document.add_heading("How this conclusion was reached", level=1)
        trace = answer.trace
        for title, value in (
            ("Searches run", "; ".join(trace.queries_issued)),
            ("Providers used", ", ".join(trace.providers_used)),
            ("Sources considered", str(trace.sources_considered)),
            ("Sources selected", str(len(trace.sources_selected))),
        ):
            if value:
                para = document.add_paragraph()
                para.add_run(f"{title}: ").bold = True
                para.add_run(value)
        for heading, items in (
            ("Assumptions", trace.assumptions),
            ("Limitations", trace.limitations),
        ):
            if items:
                document.add_heading(heading, level=2)
                for item in items:
                    document.add_paragraph(item, style="List Bullet")
        if trace.steps:
            document.add_heading("Steps", level=2)
            for step in trace.steps:
                para = document.add_paragraph(style="List Bullet")
                para.add_run(f"{step.stage}: ").bold = True
                para.add_run(step.detail)

    footer = document.add_paragraph()
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = footer.add_run(
        "Generated by the research workspace. Every statement is labelled by how it was "
        "established; nothing here replaces reading the sources."
    )
    run.italic = True
    run.font.size = Pt(8)

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def to_pdf(answer: Answer, *, style: str = "apa", include_trace: bool = True) -> bytes:
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import (
        HRFlowable, ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
    )

    def esc(text: str) -> str:
        return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, title=answer.question[:120],
        leftMargin=22 * mm, rightMargin=22 * mm, topMargin=20 * mm, bottomMargin=20 * mm,
    )
    base = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=base["BodyText"], fontSize=10, leading=15,
                          spaceAfter=6, alignment=TA_LEFT)
    small = ParagraphStyle("small", parent=body, fontSize=8, textColor=colors.HexColor("#52514e"))
    quote = ParagraphStyle("quote", parent=body, fontSize=9, leftIndent=14,
                           textColor=colors.HexColor("#52514e"), spaceBefore=2)
    h1 = ParagraphStyle("h1", parent=base["Heading1"], fontSize=15, spaceBefore=14, spaceAfter=6)
    h2 = ParagraphStyle("h2", parent=base["Heading2"], fontSize=12, spaceBefore=10, spaceAfter=4)

    status_color = {
        Epistemic.VERIFIED: "#0ca30c", Epistemic.INTERPRETATION: "#eb6834",
        Epistemic.UNCERTAIN: "#fab219", Epistemic.AI_INFERENCE: "#898781",
    }

    flow: list[Any] = [
        Paragraph(esc(answer.question), base["Title"]),
        Paragraph(
            f"{esc(answer.mode.replace('_', ' ').title())} · {answer.created_at:%d %B %Y} · "
            f"{len(answer.sources)} source(s)", small,
        ),
        HRFlowable(width="100%", color=colors.HexColor("#e1e0d9"), spaceBefore=8, spaceAfter=10),
    ]

    if answer.warnings:
        flow.append(Paragraph("Read this first", h2))
        flow.append(ListFlowable(
            [ListItem(Paragraph(esc(w), small)) for w in answer.warnings],
            bulletType="bullet", leftIndent=12,
        ))

    if answer.summary:
        flow += [Paragraph("Summary", h1), Paragraph(esc(answer.summary), body)]

    if answer.claims:
        flow += [Paragraph("Findings", h1), Paragraph(esc(DISCLAIMER), small), Spacer(1, 6)]
        for claim, marker, label in _claim_lines(answer, style):
            flow.append(Paragraph(
                f'<font color="{status_color[claim.status]}"><b>[{esc(label)}]</b></font> '
                f"{esc(claim.text)} {esc(marker)}", body,
            ))
            for citation in claim.citations:
                if citation.quote:
                    flow.append(Paragraph(f"“{esc(citation.quote.strip())}”", quote))
            if claim.verification_note:
                flow.append(Paragraph(esc(claim.verification_note), small))

    if answer.disagreements:
        flow.append(Paragraph("Where sources disagree", h1))
        for disagreement in answer.disagreements:
            flow.append(Paragraph(esc(disagreement.topic), h2))
            for position in disagreement.positions:
                titles = ", ".join(
                    (answer.source_by_id(sid).title if answer.source_by_id(sid) else sid)
                    for sid in position.source_ids
                )
                flow.append(Paragraph(f"<b>{esc(position.stance)}</b> — {esc(titles)}", body))
            if disagreement.assessment:
                flow.append(Paragraph(esc(disagreement.assessment), small))

    if answer.open_questions:
        flow.append(Paragraph("Open questions", h1))
        flow.append(ListFlowable(
            [ListItem(Paragraph(esc(q), body)) for q in answer.open_questions],
            bulletType="bullet", leftIndent=12,
        ))

    if answer.sources:
        flow.append(Paragraph("Sources", h1))
        for i, source in enumerate(answer.sources, start=1):
            flow.append(Paragraph(f"{i}. {esc(format_citation(source, style))}", body))
            if source.quality:
                flow.append(Paragraph(esc(source.quality.summary), small))

    if include_trace:
        flow.append(PageBreak())
        flow.append(Paragraph("How this conclusion was reached", h1))
        trace = answer.trace
        for title, value in (
            ("Searches run", "; ".join(trace.queries_issued)),
            ("Providers used", ", ".join(trace.providers_used)),
            ("Sources considered", str(trace.sources_considered)),
            ("Sources selected", str(len(trace.sources_selected))),
        ):
            if value:
                flow.append(Paragraph(f"<b>{esc(title)}:</b> {esc(value)}", body))
        for heading, items in (("Assumptions", trace.assumptions),
                               ("Limitations", trace.limitations)):
            if items:
                flow.append(Paragraph(heading, h2))
                flow.append(ListFlowable(
                    [ListItem(Paragraph(esc(x), small)) for x in items],
                    bulletType="bullet", leftIndent=12,
                ))
        if trace.steps:
            flow.append(Paragraph("Steps", h2))
            for step in trace.steps:
                flow.append(Paragraph(f"<b>{esc(step.stage)}</b> — {esc(step.detail)}", small))

    doc.build(flow)
    return buffer.getvalue()


def to_pptx(answer: Answer, *, style: str = "apa", max_slides: int = 20) -> bytes:
    """Slides that keep the epistemic labels — a deck should not overclaim."""
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.util import Inches, Pt

    deck = Presentation()
    deck.slide_width = Inches(13.333)
    deck.slide_height = Inches(7.5)

    title_slide = deck.slides.add_slide(deck.slide_layouts[0])
    title_slide.shapes.title.text = answer.question[:120]
    title_slide.placeholders[1].text = (
        f"{answer.mode.replace('_', ' ').title()} · {answer.created_at:%d %B %Y}\n"
        f"{len(answer.sources)} source(s) · "
        + ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in answer.confidence_breakdown.items())
    )

    if answer.summary:
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text = "Summary"
        slide.placeholders[1].text_frame.text = answer.summary[:900]

    grouped: dict[Epistemic, list[Claim]] = {}
    for claim in answer.claims:
        grouped.setdefault(claim.status, []).append(claim)

    colours = {
        Epistemic.VERIFIED: RGBColor(0x0C, 0xA3, 0x0C),
        Epistemic.INTERPRETATION: RGBColor(0xEB, 0x68, 0x34),
        Epistemic.UNCERTAIN: RGBColor(0xFA, 0xB2, 0x19),
        Epistemic.AI_INFERENCE: RGBColor(0x89, 0x87, 0x81),
    }
    numbering = {s.id: i for i, s in enumerate(answer.sources, start=1)}

    for status in (Epistemic.VERIFIED, Epistemic.INTERPRETATION,
                   Epistemic.UNCERTAIN, Epistemic.AI_INFERENCE):
        claims = grouped.get(status) or []
        for start in range(0, len(claims), 5):
            if len(deck.slides) >= max_slides:
                break
            slide = deck.slides.add_slide(deck.slide_layouts[1])
            slide.shapes.title.text = _STATUS_MARK[status]
            slide.shapes.title.text_frame.paragraphs[0].runs[0].font.color.rgb = colours[status]
            frame = slide.placeholders[1].text_frame
            frame.clear()
            for i, claim in enumerate(claims[start : start + 5]):
                para = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
                refs = " ".join(
                    f"[{numbering.get(c.source_id, '?')}]" for c in claim.citations
                )
                para.text = f"{claim.text} {refs}".strip()
                para.font.size = Pt(16)

    if answer.disagreements and len(deck.slides) < max_slides:
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text = "Where sources disagree"
        frame = slide.placeholders[1].text_frame
        frame.clear()
        for i, disagreement in enumerate(answer.disagreements[:4]):
            para = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
            para.text = disagreement.topic
            para.font.size = Pt(16)
            para.font.bold = True
            for position in disagreement.positions[:3]:
                sub = frame.add_paragraph()
                sub.text = position.stance
                sub.level = 1
                sub.font.size = Pt(13)

    if answer.sources:
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text = "Sources"
        frame = slide.placeholders[1].text_frame
        frame.clear()
        for i, source in enumerate(answer.sources[:14], start=1):
            para = frame.paragraphs[0] if i == 1 else frame.add_paragraph()
            para.text = f"[{i}] {format_citation(source, style)}"
            para.font.size = Pt(10)

    buffer = io.BytesIO()
    deck.save(buffer)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------
def export_answer(
    answer: Answer,
    fmt: Format,
    *,
    style: str = "apa",
    include_trace: bool = True,
) -> tuple[bytes, str, str]:
    """Return ``(payload, media_type, filename)``."""
    if fmt not in FORMATS:
        raise BadRequest(f"Unknown export format '{fmt}'. Known: {', '.join(FORMATS)}")
    if style not in STYLES:
        raise BadRequest(f"Unknown citation style '{style}'. Known: {', '.join(STYLES)}")

    slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in answer.question.lower())[:60]
    slug = slug.strip("-") or "research"
    stamp = f"{answer.created_at:%Y%m%d}"
    name = f"{slug}-{stamp}.{fmt if fmt != 'bibtex' else 'bib'}"

    if fmt == "md":
        return to_markdown(answer, style=style, include_trace=include_trace).encode(), MEDIA_TYPES[fmt], name
    if fmt == "txt":
        return to_text(answer, style=style).encode(), MEDIA_TYPES[fmt], name
    if fmt == "json":
        return to_json(answer).encode(), MEDIA_TYPES[fmt], name
    if fmt == "csv":
        return sources_to_csv(answer.sources, style=style).encode(), MEDIA_TYPES[fmt], name
    if fmt == "bibtex":
        return to_bibtex(answer.sources).encode(), MEDIA_TYPES[fmt], name
    if fmt == "ris":
        return to_ris(answer.sources).encode(), MEDIA_TYPES[fmt], name
    if fmt == "xlsx":
        return to_xlsx(answer, style=style), MEDIA_TYPES[fmt], name
    if fmt == "docx":
        return to_docx(answer, style=style, include_trace=include_trace), MEDIA_TYPES[fmt], name
    if fmt == "pdf":
        return to_pdf(answer, style=style, include_trace=include_trace), MEDIA_TYPES[fmt], name
    return to_pptx(answer, style=style), MEDIA_TYPES[fmt], name

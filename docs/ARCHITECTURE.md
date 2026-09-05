# Architecture

## The shape of a research turn

```
question
   │
   ├─ 1. plan        mode → source budget, providers, prompt policy
   ├─ 2. recall      search THIS project's own indexed corpus (BM25)
   ├─ 3. search      academic + web providers, concurrently
   ├─ 4. dedupe      merge the same work arriving from several providers
   ├─ 5. appraise    quality rubric → tier + explained signals
   ├─ 6. select      rank by evidence tier, then lexical relevance
   ├─ 7. deepen      fetch full text for the most promising sources
   ├─ 8. focus       keep the passages that actually bear on the question
   ├─ 9. reason      the ONLY step a model participates in
   ├─ 10. verify     strip bad citations, fix statuses, surface conflicts
   └─ 11. record     persist sources, message, timeline, index
                          │
                    Answer + Trace
```

Steps 1–8 and 10–11 are deterministic. Step 9 is the only place a model gets to
speak, and everything it produces passes through step 10 before display.

## Why the provenance model is the spine

`core/provenance.py` defines the only types that cross module boundaries:

- **`Source`** — everything needed to cite, judge and re-find something, plus
  `full_text_retrieved` and `retrieval_note` so the UI can always say how much of
  it was actually read.
- **`Passage`** — a verbatim span with a locator (page, section, timestamp,
  character offsets). Never synthesised. A citation must be re-findable by hand.
- **`Claim`** — an assertion with an `Epistemic` status, citations, a
  `support_score` and a `verification_note` explaining any downgrade.
- **`Trace`** — the audit: queries issued, providers used *and* unavailable,
  sources considered / selected / rejected-with-reasons, assumptions,
  limitations, and every step taken.
- **`Answer`** — claims + sources + disagreements + trace + warnings.

Because the trace is a first-class part of the answer rather than a log, the
"How did you reach this conclusion?" panel and the trace sheet in the Excel
export are the same data.

## The provider registry

`core/registry.py` maps a **capability** (`llm`, `web_search`,
`academic_search`, `url_extract`, `document_parse`, `ocr`, `video_transcript`,
`passage_index`, `blob_storage`) to ordered adapters.

Three properties matter:

1. **Lazy registration.** Adapters are constructed on first use. A broken
   optional dependency downgrades one capability rather than preventing boot.
2. **Honest status.** Every adapter reports `available` plus a *reason* when it
   is not. `/api/providers` renders these, and the reasons are copied verbatim
   into any answer that was affected.
3. **Resolution by config.** `registry.resolve("web_search", spec)` turns
   `"auto"` / `"none"` / `"tavily,brave"` into an ordered list of *available*
   providers. Callers never name a vendor.

Failures during a search are gathered, not raised: `retrieval._gather` records
each one in `trace.providers_unavailable` and continues with what worked.

## The verification layer in detail

`services/grounding.py`. `RetrievalSet` is the universe of citable things for
one turn: sources plus their `S1…Sn` display labels. It renders the prompt
context *and* resolves the model's citations, so the two can never drift apart.

`verify_claim` does five things in order:

1. Resolve each cited label. Unresolvable → dropped and recorded.
2. If the model supplied a quote, locate it verbatim (with a punctuation-
   insensitive second pass). Not found → the quote is discarded, and a real
   supporting passage is looked for instead.
3. Score wording overlap between claim and passage. Below `SUPPORT_FLOOR`
   (0.18) the citation is dropped as unrelated.
4. Set the final status: no citations → `ai_inference`; `verified` with overlap
   below `VERIFIED_FLOOR` (0.45) → `interpretation`.
5. Record why, in `verification_note`, in language the reader can act on.

`verify_answer` adds `strip_fabricated_dois`, conflict annotation (a claim
contradicted by another retrieved source becomes `uncertain` and lists who
disputes it), and coverage warnings — thin evidence, single-source support,
abstract-only sources, unreadable sources.

## Source quality without a score

`services/source_quality.py` deliberately returns a **list of explained
signals** plus a tier, never a number. Eight dimensions: retraction status, peer
review, evidence type, publisher standing, authorship, recency, scholarly
uptake, evidence access, and conflicts of interest. Each carries a verdict
(`strong` / `adequate` / `weak` / `unknown` / `caution`) and a sentence of
reasoning that appears in the source drawer.

Two design choices worth noting:

- Missing metadata reads as `unknown`, never as bad. An undated page is not
  penalised as though it were old.
- A recent paper with few citations is `unknown`, not `weak` — citation counts
  lag publication by a year or more, so a low count on a new paper says nothing.

## Statistics that refuse to overclaim

`services/analysis.py`:

- Missing values are **counted and located, never imputed**. Every test reports
  how many rows it dropped.
- Test selection is driven by *checked* assumptions: Shapiro-Wilk (or
  D'Agostino above n=5000) per group, Levene for variance. Non-normal data
  switches to a rank-based test automatically, and the switch is visible.
- A constant column is reported as constant rather than "normal".
- Every result carries an effect size, the assumptions with their verdicts, and
  runnable code that re-derives exactly those numbers.
- An omnibus test always warns that it is not pairwise.

## Charts

One `ChartSpec` drives two renderers: an interactive SVG in the browser and
matplotlib server-side for PNG/SVG/PDF export, so the screen and the exported
figure agree.

`services/palette.py` holds a CVD-validated categorical palette in **fixed slot
order** — the ordering is the colourblind-safety mechanism, so it must not be
reshuffled. Scatter-type forms compare all pairs at once and cap at three
series; beyond that the chart facets or folds into "Other". Slots that fall
below 3:1 contrast on the light surface trigger the *relief rule*: direct value
labels plus a table view, so identity never rests on colour alone.

## Project memory

`services/memory.py` + `providers/index/sqlite_fts.py`. Every passage of every
source in a project is indexed in SQLite FTS5. "According to the papers I
uploaded earlier…" is answered by a BM25 search over that corpus, and the answer
shows which passages matched — so you can see whether retrieval found the right
material rather than trusting that it did.

Sources de-duplicate by DOI → PMID → arXiv → normalised URL → title, and merge
field-by-field: the same paper arriving from OpenAlex and from a PDF upload
becomes one source carrying the better metadata of the two. Because the same
paper can live in several projects, adding it mints a project-scoped id, and the
orchestrator re-points the answer's citations at the stored rows.

## Replacing a provider

1. Subclass the capability's base class in `providers/<capability>/`.
2. Implement `status()` — return a *reason* when unavailable.
3. Register it lazily in `providers/__init__.py`.
4. Select it in `.env`.

Nothing in `services/` changes.

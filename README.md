# Lumen — an evidence-first research workspace

Give it a question, a URL, a paper, an image, a dataset or a video, and it turns
that into research you can check.

Every output answers three questions:

> **What did you find? · Where did it come from? · How certain are we?**

---

## The idea

Most AI research tools are fluent and unfalsifiable. This one is built the other
way round: the model is one stage in a pipeline, and everything it writes is
**mechanically checked against the sources that were actually retrieved** before
a person sees it.

Concretely, in `services/grounding.py`:

| Rule | What happens |
|---|---|
| A citation may only name a retrieved source | `[S7]` when only S1–S4 exist is stripped, and the claim is demoted to *AI inference* |
| A quote must appear in the cited source | quotes that aren't in the text are removed |
| Wording must overlap its cited passage | a "verified" claim that barely matches becomes *interpretation* |
| A claim with no surviving citation is not a finding | it is labelled *AI inference* everywhere it appears |
| DOIs are only echoed from retrieved metadata | invented DOIs are deleted and the deletion is reported |
| Conflicts are shown, not averaged | disagreeing sources produce a *contested* label |

So the four labels — **Verified · Interpretation · Uncertain · AI inference** —
are assigned by the verifier, not claimed by the model. They survive into every
export: the PDF, the Word document, the slides and the spreadsheet all carry
them.

## It works with no API keys at all

With zero credentials configured, the workspace still:

- searches **OpenAlex, Europe PMC, Crossref and arXiv** (all free, no key)
- fetches and parses web pages, PDFs, DOCX, CSV/Excel and video transcripts
- ranks sources by an **explained** quality rubric (never a single opaque score)
- indexes everything into a per-project BM25 corpus you can ask questions of
- runs statistics with assumption checks, and draws publication-quality figures
- formats citations in APA, MLA, Chicago, IEEE, Vancouver and BibTeX
- exports to PDF, DOCX, Markdown, TXT, CSV, XLSX, PPTX, BibTeX, RIS and JSON

What it *won't* do without a reasoning model is write prose. Instead it answers
by quoting the passages it retrieved, labels them as extractive, and tells you
which key to set. Nothing is ever generated to paper over a missing capability —
see `/api/providers` for exactly what is on and why anything is off.

Add `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` and synthesis, image analysis,
diagram authoring, paper analysis and the Skeptic mode switch on.

---

## Quick start

### With Docker — one command

Needs a machine with a real Linux kernel: Linux, macOS or Windows with Docker
Desktop, or a VPS. **Docker cannot run inside Termux on Android** — it needs
control of kernel namespaces and cgroups that Android does not hand to a
userland app. See [Running on Android](#running-on-android) instead.

```bash
git clone -b claude/assalamu-aleikum-nrg1aa https://github.com/Firephase/Barbiegame.git
cd Barbiegame
docker compose up --build          # or: make up
```

Open **http://localhost:8000**. The UI and the API are served from the same
port, so there is nothing else to wire up. Uploads and the database live in a
named volume and survive a rebuild.

To add keys, drop a `.env` beside `docker-compose.yml` before starting (see
`.env.example`) — compose reads it automatically.

The image also installs Tesseract, so OCR for scanned PDFs and photographed
notes works out of the box, which it does not in a bare local install.

### Without Docker

```bash
make install                      # venv + npm install
cp .env.example .env              # optional: add keys
make dev                          # API on :8000, UI on :5173
```

Open http://localhost:5173. Needs Python 3.11+ and Node 18+.

Either way: API docs at `/docs`, and a live report of what is switched on — and
*why* anything is off — at `/api/providers`.

```bash
make test                         # 82 backend tests, no network needed
make typecheck                    # frontend
```

### Running on Android

Termux alone is not enough: the scientific stack (NumPy, pandas, SciPy,
matplotlib) has no Termux-native builds, and Docker cannot run there at all.
What does work is a Linux userland under `proot-distro`, where pip finds
prebuilt `aarch64` wheels for every dependency and nothing has to compile.

```bash
# --- in Termux ---
pkg update -y && pkg install -y proot-distro
proot-distro install ubuntu
proot-distro login ubuntu

# --- now inside Ubuntu ---
apt update && apt install -y python3 python3-venv python3-pip git nodejs npm
git clone -b claude/assalamu-aleikum-nrg1aa https://github.com/Firephase/Barbiegame.git
cd Barbiegame

python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -r backend/requirements.txt

cd frontend && npm install && npm run build && cd ..
cd backend && ../.venv/bin/uvicorn app.main:app --port 8000
```

Then open **http://localhost:8000** in the phone's browser — the API serves the
UI it just built, so one port is all you need.

Expect roughly 400–500 MB of downloads and a slow first build; do it on wi-fi
and on charge. After the first run, starting it again is just the last two
lines. To skip the UI build entirely, run only the `uvicorn` line and use the
API through `/docs`.

---

## What's in it

| Area | Where | Notes |
|---|---|---|
| **Web + academic search** | `providers/search`, `providers/academic` | Tavily · Brave · Serper · SearXNG · Wikipedia; OpenAlex · Europe PMC · Crossref · arXiv · Semantic Scholar |
| **URL reading** | `providers/extract` | robots.txt-respecting; pulls metadata, tables and references |
| **Video research** | `providers/video` | published captions only, timestamp-anchored claims |
| **Documents & OCR** | `providers/documents` | PDF (page-anchored), DOCX, CSV/TSV/Excel, text; Tesseract when installed |
| **Anti-hallucination** | `services/grounding.py` | the rules table above |
| **Source appraisal** | `services/source_quality.py` | 8 explained dimensions → a tier, plus caveats |
| **Citations** | `services/citations.py` | 6 styles; never invents a missing year or author |
| **Paper analysis** | `services/papers.py` | IMRaD split + 4 explanation levels + multi-paper synthesis |
| **Statistics** | `services/analysis.py` | assumption-checked tests, reproducible code, no imputation |
| **Charts** | `services/charts.py`, `services/palette.py` | 17 forms; CVD-validated palette shared by browser and matplotlib |
| **Diagrams** | `services/diagrams.py` | Mermaid, validated before it is returned, revisable in natural language |
| **Knowledge graph** | `services/knowledge_graph.py` | built from real metadata and verified claims only |
| **Project memory** | `services/memory.py` | per-project BM25 index over everything you've collected |
| **Export** | `services/export.py` | 10 formats, all keeping citations and confidence labels |

### Research modes

`Quick answer` · `Deep research` · `Paper analyst` · `Data analyst` ·
`Image analyst` · `Scientific writer` · `Skeptic / reviewer` · `Teacher`

A mode is a policy — how many sources, which providers, how much text, what to
prioritise — declared as data in `services/modes.py`, not a separate code path.

---

## Architecture

```
backend/app/
├── core/          registry · provenance model · errors · text
├── providers/     every external service, behind a capability interface
├── services/      the research logic; imports no vendor SDK
├── api/routes/    49 HTTP endpoints
└── models.py      project · sources · messages · artifacts · notes · findings
frontend/src/
├── components/    AnswerView · TracePanel · Chart · AskBar · workspace tabs
└── api.ts         typed client that surfaces backend reasons verbatim
```

Nothing outside `providers/` knows which vendor is in use. Swapping search
engines, models or storage is a `.env` change; adding one is a new adapter plus
one line in `providers/__init__.py`. Providers register lazily, so a missing
optional dependency degrades one capability instead of breaking startup.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the detail.

---

## Honest limits

- **The verifier is lexical, not semantic.** It reliably catches citations to
  sources that were never retrieved, quotes that don't exist, and claims with no
  textual support. It cannot catch a subtly wrong paraphrase of a passage that
  *is* there. It sets a floor, not a ceiling.
- **Full text is often unavailable.** Paywalled work contributes its abstract
  only, and every answer says when that is what it rests on.
- **Source-quality signals describe provenance, not correctness.** A
  peer-reviewed paper can be wrong; a blog can be right. The rubric tells you
  what kind of scrutiny a claim has had, and shows its reasoning so you can
  disagree with it.
- **No authentication yet.** Run it locally or behind your own auth layer;
  `providers/storage` and the project model are ready for a multi-user layer but
  it isn't written.
- **Respect the sources.** The fetcher honours robots.txt and rate limits, uses
  official APIs where they exist, and does not attempt to bypass paywalls or
  logins.

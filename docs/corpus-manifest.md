# Corpus manifest

One row per source document. Fill the licence column before ingesting; the ingestion CLI also
writes a machine-readable record to `data/index/manifest.json` (title, corpus, licence, SHA-256,
chunk count, time). Rows below mirror [../PROJECT_SPEC.md](../PROJECT_SPEC.md) Section 19.5.

| Document | Corpus | File in `data/raw/` | Licence (verify) | Permission | Ingested |
|---|---|---|---|---|---|
| *Think Python: How to Think Like a Computer Scientist*, version 2.0.17 (2012, Allen Downey), 240 pages | `fundamentals` | `thinkpython.pdf` (you provide) | Creative Commons Attribution-NonCommercial 3.0 Unported, stated on page 4 of the PDF. Non-commercial | Required if the product is commercial | yes, 338 chunks |
| Kurniawan et al., *Steps Before Syntax* (arXiv:2109.08896) | `pedagogy` | `pcdit_paper.pdf` (you provide) | Not stated in the PDF (arXiv:2109.08896v1) | Author permission still needed before learner-facing use | yes, 29 chunks |
| PCDIT framework page, okakurniawan.net/pcdit-framework | `pedagogy` | not downloaded | None stated | Ask the author before ingesting | no |
| Python tutorial (docs.python.org) | `fundamentals` | optional | PSF licence | none needed | no |
| `data/sample/python_basics.md` | `fundamentals` | in repo | Original text written for tests | none | tests and demo only |
| `data/sample/pcdit_notes.md` | `pedagogy` | in repo | Original paraphrase for tests | none | tests only |

Recorded in `data/index/manifest.json` (ingested 2026-10-30):

| File | SHA-256 | Chunks |
|---|---|---|
| `thinkpython.pdf` | `c518caa7131357c43117698fffdf720bc3256bc31d283cb9d1e81f3a9c180d6a` | 338 |
| `pcdit_paper.pdf` | `d301d478b93fd14c77265d02b8fb0355aed219b71245c38f2bda460ace0412fd` | 29 |

## Rules

- `pedagogy` material is never quoted to learners. Cite it by method name only.
- Do not commit files in `data/raw/` or `data/index/` (both are gitignored).
- After ingesting, copy the licence and hash from `data/index/manifest.json` here if you want a
  human-readable record, and tick the Ingested column.
- Changing a document: see "Known limitations" in [rag-and-ingestion.md](rag-and-ingestion.md).

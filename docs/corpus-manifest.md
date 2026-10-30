# Corpus manifest

One row per source document. Fill the licence column before ingesting; the ingestion CLI also
writes a machine-readable record to `data/index/manifest.json` (title, corpus, licence, SHA-256,
chunk count, time). Rows below mirror [../PROJECT_SPEC.md](../PROJECT_SPEC.md) Section 19.5.

| Document | Corpus | File in `data/raw/` | Licence (verify) | Permission | Ingested |
|---|---|---|---|---|---|
| *Think Python*, 2nd edition (Allen Downey) | `fundamentals` | `think_python.pdf` (you provide) | Believed CC BY-NC-SA 3.0. Non-commercial. Confirm on the edition's licence page | Required if the product is commercial | no |
| Kurniawan et al., *Steps Before Syntax* (arXiv:2109.08896) | `pedagogy` | `pcdit_paper.pdf` (you provide) | Check the licence field on the arXiv page | Confirm with the authors before learner-facing use | no |
| PCDIT framework page, okakurniawan.net/pcdit-framework | `pedagogy` | not downloaded | None stated | Ask the author before ingesting | no |
| Python tutorial (docs.python.org) | `fundamentals` | optional | PSF licence | none needed | no |
| `data/sample/python_basics.md` | `fundamentals` | in repo | Original text written for tests | none | tests and demo only |
| `data/sample/pcdit_notes.md` | `pedagogy` | in repo | Original paraphrase for tests | none | tests only |

## Rules

- `pedagogy` material is never quoted to learners. Cite it by method name only.
- Do not commit files in `data/raw/` or `data/index/` (both are gitignored).
- After ingesting, copy the licence and hash from `data/index/manifest.json` here if you want a
  human-readable record, and tick the Ingested column.
- Changing a document: see "Known limitations" in [rag-and-ingestion.md](rag-and-ingestion.md).

"""Ingestion: load -> Markdown -> chunk -> embed -> idempotent upsert (spec 9.2).

CLI:
    uv run python -m codebuddy.rag.ingest data/raw/thinkpython.pdf \
        --corpus fundamentals --title "Think Python" --licence "CC BY-NC 3.0 Unported"
"""

from __future__ import annotations

import argparse
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore

from codebuddy.config import Settings, get_settings
from codebuddy.rag.chunking import chunk_markdown
from codebuddy.rag.manifest import Manifest, ManifestEntry, file_sha256

SUPPORTED = {".md", ".markdown", ".txt", ".html", ".htm", ".pdf"}


class _HtmlToMarkdown(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out: list[str] = []
        self._skip = 0
        self._pre = False

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self._skip += 1
        elif tag in {"h1", "h2", "h3", "h4"}:
            self.out.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "pre":
            self._pre = True
            self.out.append("\n\n```\n")
        elif tag in {"p", "div", "li", "br"}:
            self.out.append("\n\n" if tag != "li" else "\n- ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self._skip = max(0, self._skip - 1)
        elif tag in {"h1", "h2", "h3", "h4"}:
            self.out.append("\n\n")
        elif tag == "pre":
            self._pre = False
            self.out.append("\n```\n\n")

    def handle_data(self, data):
        if self._skip:
            return
        self.out.append(data if self._pre else re.sub(r"\s+", " ", data))


def html_to_markdown(html: str) -> str:
    parser = _HtmlToMarkdown()
    parser.feed(html)
    return re.sub(r"\n{3,}", "\n\n", "".join(parser.out)).strip()


def tidy_docling_markdown(markdown: str) -> str:
    """Docling writes every heading as '##'. A line starting with a single '#' is a comment
    from an unfenced code listing, so indent it to keep it from being read as a heading."""
    return re.sub(r"(?m)^# ", "    # ", markdown)


def pdf_to_markdown(path: Path) -> str:  # pragma: no cover - needs the pdf extra
    try:
        from docling.document_converter import DocumentConverter
    except ImportError as exc:
        raise RuntimeError("PDF ingestion needs the extra: uv sync --extra pdf") from exc
    markdown = DocumentConverter().convert(str(path)).document.export_to_markdown()
    return tidy_docling_markdown(markdown)


def load_markdown(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return pdf_to_markdown(path)
    text = path.read_text(encoding="utf-8")
    return html_to_markdown(text) if suffix in {".html", ".htm"} else text


def ingest_file(
    path: Path,
    *,
    corpus: str,
    store: QdrantVectorStore,
    manifest: Manifest,
    settings: Settings,
    title: str | None = None,
    licence: str = "unverified",
    language: str = "python",
    difficulty: str = "beginner",
    pcdit_stage: str | None = None,
    force: bool = False,
) -> int:
    """Returns the number of chunks upserted (0 when the file is unchanged)."""
    sha = file_sha256(path)
    if not force and manifest.is_current(corpus, path.name, sha):
        return 0
    base = {
        "source": path.name,
        "title": title or path.stem.replace("_", " ").title(),
        "corpus": corpus,
        "license": licence,
        "language": language,
        "difficulty": difficulty,
        "version": settings.index_version,
        "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    if pcdit_stage:
        base["pcdit_stage"] = pcdit_stage
    chunks = chunk_markdown(load_markdown(path), base)
    docs = [Document(page_content=c.text, metadata=c.meta) for c in chunks]
    if docs:
        store.add_documents(docs, ids=[c.id for c in chunks])
    manifest.record(
        ManifestEntry(
            source=path.name,
            title=base["title"],
            corpus=corpus,
            licence=licence,
            sha256=sha,
            chunks=len(chunks),
            ingested_at=base["updated_at"],
        )
    )
    return len(chunks)


def main(argv: list[str] | None = None) -> None:  # pragma: no cover - needs live OpenAI
    from dotenv import load_dotenv
    from langchain_openai import OpenAIEmbeddings
    from langchain_qdrant import FastEmbedSparse

    load_dotenv()  # SDKs read OPENAI_API_KEY from the environment, not from Settings

    from codebuddy.rag.store import get_store, make_client

    ap = argparse.ArgumentParser(description="Ingest documents into a CodeBuddy corpus")
    ap.add_argument("path", type=Path, help="file or folder")
    ap.add_argument("--corpus", default="fundamentals")
    ap.add_argument("--title")
    ap.add_argument("--licence", default="unverified")
    ap.add_argument("--language", default="python")
    ap.add_argument("--difficulty", default="beginner")
    ap.add_argument("--pcdit-stage")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    if not args.path.exists():
        ap.error(f"no such file or folder: {args.path}")

    settings = get_settings()
    client = make_client(settings)
    store = get_store(
        args.corpus,
        client,
        OpenAIEmbeddings(model=settings.embed_model),
        FastEmbedSparse(model_name="Qdrant/bm25"),
        settings,
    )
    manifest = Manifest(Path(settings.qdrant_path) / "manifest.json")
    files = (
        [args.path]
        if args.path.is_file()
        else sorted(p for p in args.path.rglob("*") if p.suffix.lower() in SUPPORTED)
    )
    for f in files:
        n = ingest_file(
            f,
            corpus=args.corpus,
            store=store,
            manifest=manifest,
            settings=settings,
            title=args.title if len(files) == 1 else None,
            licence=args.licence,
            language=args.language,
            difficulty=args.difficulty,
            pcdit_stage=args.pcdit_stage,
            force=args.force,
        )
        print(f"{f}: {n} chunks" if n else f"{f}: unchanged, skipped")


if __name__ == "__main__":  # pragma: no cover
    main()

"""Structure-aware Markdown chunking (spec 9.2).

- Splits on headings, never inside a fenced code block.
- Packs blocks to roughly 200-500 tokens (about 4 characters per token).
- Keeps the parent section so retrieval can return small-to-big context.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field

TARGET_MIN_CHARS = 800
TARGET_MAX_CHARS = 2000
_HEADING = re.compile(r"^(#{1,4})\s+(.*\S)\s*$")
_FENCE = re.compile(r"^\s*```")


@dataclass
class Chunk:
    text: str
    meta: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        """Deterministic UUID so re-ingesting the same text overwrites instead of duplicating."""
        return str(uuid.uuid5(uuid.NAMESPACE_URL, self.meta.get("content_hash", self.text)))


def _blocks(lines: list[str]) -> list[str]:
    """Paragraphs and whole fenced code blocks."""
    blocks: list[str] = []
    cur: list[str] = []
    in_fence = False
    for line in lines:
        if _FENCE.match(line):
            if not in_fence and cur:
                blocks.append("\n".join(cur).strip())
                cur = []
            cur.append(line)
            if in_fence:
                blocks.append("\n".join(cur).strip())
                cur = []
            in_fence = not in_fence
            continue
        if in_fence:
            cur.append(line)
        elif line.strip() == "":
            if cur:
                blocks.append("\n".join(cur).strip())
                cur = []
        else:
            cur.append(line)
    if cur:
        blocks.append("\n".join(cur).strip())
    return [b for b in blocks if b]


def _sections(markdown: str) -> list[tuple[list[str], list[str]]]:
    """(heading path, body lines) per section."""
    sections: list[tuple[list[str], list[str]]] = []
    path: list[str] = []
    body: list[str] = []
    in_fence = False
    for line in markdown.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
        m = None if in_fence else _HEADING.match(line)
        if m:
            if body:
                sections.append((list(path), body))
                body = []
            depth = len(m.group(1))
            path = path[: depth - 1] + [m.group(2)]
        else:
            body.append(line)
    if body:
        sections.append((list(path), body))
    return sections


def _content_type(path: list[str], text: str) -> str:
    heading = " ".join(path).lower()
    if "exercise" in heading:
        return "exercise"
    if any(w in heading for w in ("debug", "common error", "pitfall", "mistake")):
        return "common-bug"
    if "```" in text:
        return "example"
    return "explanation"


def chunk_markdown(markdown: str, base_meta: dict) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path, lines in _sections(markdown):
        blocks = _blocks(lines)
        if not blocks:
            continue
        section_text = "\n\n".join(blocks)
        parent = section_text[: TARGET_MAX_CHARS * 3]
        packs: list[list[str]] = []
        cur: list[str] = []
        size = 0
        for block in blocks:
            if cur and size + len(block) > TARGET_MAX_CHARS:
                packs.append(cur)
                cur, size = [], 0
            cur.append(block)
            size += len(block)
        if cur:
            if packs and size < TARGET_MIN_CHARS // 2:
                packs[-1].extend(cur)  # fold a tiny tail into the previous chunk
            else:
                packs.append(cur)

        title = " › ".join(path) if path else base_meta.get("title", "")
        for pack in packs:
            body = "\n\n".join(pack)
            prefix = f"From {base_meta.get('title', 'source')}, {title}:\n" if title else ""
            text = prefix + body
            meta = {
                **base_meta,
                "chapter": path[0] if path else "",
                "concept": path[-1].lower() if path else "",
                "section": title,
                "content_type": _content_type(path, body),
                "parent": parent,
                "content_hash": hashlib.sha256(
                    (base_meta.get("source", "") + text).encode()
                ).hexdigest(),
            }
            chunks.append(Chunk(text=text, meta=meta))
    return chunks

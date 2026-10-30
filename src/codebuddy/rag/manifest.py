"""Corpus manifest: what was ingested, from where, under which licence (spec 19.5)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class ManifestEntry:
    source: str
    title: str
    corpus: str
    licence: str
    sha256: str
    chunks: int
    ingested_at: str


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class Manifest:
    def __init__(self, path: Path):
        self.path = path
        self._entries: dict[str, ManifestEntry] = {}
        if path.exists():
            raw = json.loads(path.read_text())
            self._entries = {k: ManifestEntry(**v) for k, v in raw.items()}

    def key(self, corpus: str, source: str) -> str:
        return f"{corpus}::{source}"

    def is_current(self, corpus: str, source: str, sha256: str) -> bool:
        entry = self._entries.get(self.key(corpus, source))
        return entry is not None and entry.sha256 == sha256

    def record(self, entry: ManifestEntry) -> None:
        self._entries[self.key(entry.corpus, entry.source)] = entry
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({k: asdict(v) for k, v in self._entries.items()}, indent=2) + "\n"
        )

    def entries(self) -> list[ManifestEntry]:
        return list(self._entries.values())

"""Corpus manifest: what was ingested, from where, under which licence (spec 19.5)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from codebuddy.config import Settings
from codebuddy.rag.store import qdrant_host


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


LEGACY = "legacy"


def manifest_target(settings: Settings) -> str:
    """Id of where the index lives: embedded folder or server host (never a key or full URL),
    plus collection prefix and index version, so each target keeps its own record."""
    where = (
        f"server:{qdrant_host(settings.qdrant_url)}"
        if settings.qdrant_url
        else f"embedded:{settings.qdrant_path}"
    )
    return f"{where}|{settings.qdrant_collection_prefix}|{settings.index_version}"


class Manifest:
    """Per-target record of ingested files. File format 2:
    {"format": 2, "targets": {target_id: {"corpus::source": entry}}}.
    The old flat format (one dict of entries) is read as belonging to the embedded index
    next to this file and rewritten in the new format on the next write."""

    def __init__(self, path: Path, target: str = "default"):
        self.path = path
        self.target = target
        self._targets: dict[str, dict[str, ManifestEntry]] = {}
        if path.exists():
            raw = json.loads(path.read_text())
            if raw.get("format") == 2:
                self._targets = {
                    t: {k: ManifestEntry(**v) for k, v in es.items()}
                    for t, es in raw["targets"].items()
                }
            else:  # old flat format: only an embedded index could have written it
                self._targets = {LEGACY: {k: ManifestEntry(**v) for k, v in raw.items()}}
        if target.startswith("embedded:") and LEGACY in self._targets:
            adopted = self._targets.pop(LEGACY)
            for k, v in adopted.items():
                self._targets.setdefault(target, {}).setdefault(k, v)

    @property
    def _entries(self) -> dict[str, ManifestEntry]:
        return self._targets.setdefault(self.target, {})

    def key(self, corpus: str, source: str) -> str:
        return f"{corpus}::{source}"

    def is_current(self, corpus: str, source: str, sha256: str) -> bool:
        entry = self._entries.get(self.key(corpus, source))
        return entry is not None and entry.sha256 == sha256

    def record(self, entry: ManifestEntry) -> None:
        self._entries[self.key(entry.corpus, entry.source)] = entry
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "format": 2,
            "targets": {
                t: {k: asdict(v) for k, v in es.items()} for t, es in self._targets.items()
            },
        }
        self.path.write_text(json.dumps(data, indent=2) + "\n")

    def entries(self) -> list[ManifestEntry]:
        """Entries of the current target."""
        return list(self._entries.values())

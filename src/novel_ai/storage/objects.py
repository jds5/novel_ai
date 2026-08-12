from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class StoredObject:
    uri: str
    sha256: str
    compressed_size: int


class LocalObjectStore:
    """Content-addressed local store used for non-canonical raw provider payloads."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def put_json(self, namespace: str, value: dict[str, Any]) -> StoredObject:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        relative = Path(namespace) / digest[:2] / f"{digest}.json.gz"
        target = self._root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            temporary_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb", dir=target.parent, prefix=".writing-", delete=False
                ) as temporary:
                    temporary_path = Path(temporary.name)
                    with gzip.GzipFile(fileobj=temporary, mode="wb", mtime=0) as compressed:
                        compressed.write(encoded)
                os.replace(temporary_path, target)
            finally:
                if temporary_path is not None and temporary_path.exists():
                    temporary_path.unlink()
        return StoredObject(
            uri=f"objects://{relative.as_posix()}",
            sha256=digest,
            compressed_size=target.stat().st_size,
        )

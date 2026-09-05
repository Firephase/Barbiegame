"""Local filesystem blob storage.

Content-addressed so re-uploading the same file is free and every stored
artifact has a stable, verifiable identity.
"""
from __future__ import annotations

import hashlib
import mimetypes
import shutil
from dataclasses import dataclass
from pathlib import Path

from ...config import settings
from ...core.errors import NotFound
from ...core.registry import Provider, ProviderStatus

CAPABILITY = "blob_storage"


@dataclass(slots=True)
class StoredBlob:
    key: str
    path: Path
    size: int
    media_type: str
    sha256: str


class LocalStorage(Provider):
    capability = CAPABILITY
    name = "local"
    requires_credentials = False
    priority = 10

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or settings.uploads_dir
        self.root.mkdir(parents=True, exist_ok=True)

    def status(self) -> ProviderStatus:
        writable = self.root.exists()
        try:
            probe = self.root / ".write-probe"
            probe.write_text("ok")
            probe.unlink()
        except OSError as exc:
            return ProviderStatus(False, f"{self.root} is not writable: {exc}")
        return ProviderStatus(writable, details={"root": str(self.root)})

    def put(self, data: bytes, filename: str) -> StoredBlob:
        digest = hashlib.sha256(data).hexdigest()
        suffix = Path(filename).suffix.lower()
        key = f"{digest}{suffix}"
        target = self.root / digest[:2] / key
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(data)
        media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return StoredBlob(key=key, path=target, size=len(data), media_type=media_type, sha256=digest)

    def path_for(self, key: str) -> Path:
        digest = key.split(".")[0]
        path = self.root / digest[:2] / key
        if not path.exists():
            raise NotFound(f"Stored file '{key}' no longer exists on disk.")
        return path

    def read(self, key: str) -> bytes:
        return self.path_for(key).read_bytes()

    def delete(self, key: str) -> bool:
        try:
            self.path_for(key).unlink()
            return True
        except NotFound:
            return False

    def usage_bytes(self) -> int:
        return sum(f.stat().st_size for f in self.root.rglob("*") if f.is_file())

    def clear(self) -> None:  # pragma: no cover - test helper
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)

import json
from pathlib import Path

from pydantic import ValidationError

from app.updater_schemas import UpdateManifest, UpdateManifestEntry


class UpdateManifestRepository:
    def __init__(self, manifest_path: str) -> None:
        self.manifest_path = Path(manifest_path)
        self._entries: dict[str, UpdateManifestEntry] | None = None

    def load(self) -> None:
        with self.manifest_path.open("r", encoding="utf-8") as fp:
            payload = json.load(fp)
        try:
            manifest = UpdateManifest(entries=payload)
        except ValidationError as exc:
            raise ValueError(f"invalid update manifest: {exc}") from exc
        self._entries = manifest.entries

    def get(self, key: str) -> UpdateManifestEntry | None:
        if self._entries is None:
            raise RuntimeError("update manifest is not loaded")
        return self._entries.get(key)

import re
from hashlib import sha256
from pathlib import Path

from scripts.generate_update_manifest import generate_manifest

def test_generate_update_manifest_script() -> None:
    fixtures_dir = Path(__file__).resolve().parent / "fixtures"
    manifest = generate_manifest(fixtures_dir / "release_spec.json")

    entry = manifest.entries["windows:x64"]
    artifact_bytes = (fixtures_dir / "release_artifact.bin").read_bytes()
    assert manifest.model_dump(mode="json")["entries"]["windows:x64"]["latest_version"] == "2.3.0"
    assert entry.latest_build == 12
    assert entry.download_url == "https://download.example.com/OneTJSetup_2.3.0_12.exe"
    assert entry.sha256 == sha256(artifact_bytes).hexdigest()
    assert entry.file_size == len(artifact_bytes)
    assert entry.release_notes == (fixtures_dir / "release_notes.md").read_text(encoding="utf-8").strip()
    assert entry.min_supported_version == "2.0.0"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", manifest.model_dump(mode="json")["entries"]["windows:x64"]["published_at"])

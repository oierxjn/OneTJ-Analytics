import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.updater_schemas import UpdateManifest, UpdateManifestEntry


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate update_manifest.json from a release spec and local artifacts."
    )
    parser.add_argument(
        "--spec",
        default="config/release_spec.json",
        help="Path to the release spec JSON file.",
    )
    parser.add_argument(
        "--output",
        default="config/update_manifest.json",
        help="Path to the generated manifest JSON file.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Write compact JSON without indentation.",
    )
    return parser.parse_args()


def compute_sha256(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_input_file(file_value: object, key: str, field_name: str, base_dir: Path) -> Path:
    if not isinstance(file_value, str) or not file_value.strip():
        raise ValueError(f"{key}.{field_name} must be a non-empty string")
    file_path = Path(file_value)
    if not file_path.is_absolute():
        file_path = (base_dir / file_path).resolve()
    if not file_path.is_file():
        raise ValueError(f"{key}.{field_name} does not exist: {file_path}")
    return file_path


def resolve_release_notes(key: str, raw_entry: dict[str, Any], spec_dir: Path) -> str | None:
    inline_notes = raw_entry.get("release_notes")
    notes_file_value = raw_entry.get("release_notes_file")

    if inline_notes is not None and notes_file_value is not None:
        raise ValueError(f"{key} cannot set both release_notes and release_notes_file")
    if inline_notes is not None:
        if not isinstance(inline_notes, str) or not inline_notes.strip():
            raise ValueError(f"{key}.release_notes must be a non-empty string")
        return inline_notes.strip()
    if notes_file_value is None:
        return None

    notes_file_path = resolve_input_file(notes_file_value, key, "release_notes_file", spec_dir)
    return notes_file_path.read_text(encoding="utf-8").strip()


def build_entry(key: str, raw_entry: dict[str, Any], spec_dir: Path) -> UpdateManifestEntry:
    artifact_value = raw_entry.get("artifact_path")
    artifact_path = resolve_input_file(artifact_value, key, "artifact_path", spec_dir)

    latest_version = raw_entry.get("version")
    latest_build = raw_entry.get("build")
    download_url = raw_entry.get("download_url")

    if not isinstance(latest_version, str) or not latest_version.strip():
        raise ValueError(f"{key}.version must be a non-empty string")
    if not isinstance(latest_build, int):
        raise ValueError(f"{key}.build must be an integer")
    if not isinstance(download_url, str) or not download_url.strip():
        raise ValueError(f"{key}.download_url must be a non-empty string")

    entry_payload: dict[str, Any] = {
        "latest_version": latest_version.strip(),
        "latest_build": latest_build,
        "download_url": download_url.strip(),
        "sha256": compute_sha256(artifact_path),
        "file_size": artifact_path.stat().st_size,
        "published_at": normalize_published_at(raw_entry.get("published_at")),
    }

    release_notes = resolve_release_notes(key, raw_entry, spec_dir)
    if release_notes is not None:
        entry_payload["release_notes"] = release_notes

    optional_mapping = {
        "mandatory": "mandatory",
        "min_supported_version": "min_supported_version",
    }
    for source_key, target_key in optional_mapping.items():
        value = raw_entry.get(source_key)
        if value is not None:
            entry_payload[target_key] = value
    return UpdateManifestEntry(**entry_payload)


def normalize_published_at(value: object) -> str:
    if value is None:
        return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("published_at must be a non-empty string when provided")
    return value.strip()


def load_spec(spec_path: Path) -> dict[str, Any]:
    with spec_path.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)
    if not isinstance(payload, dict):
        raise ValueError("spec root must be a JSON object")
    return payload


def generate_manifest(spec_path: Path) -> UpdateManifest:
    payload = load_spec(spec_path)
    entries_value = payload.get("entries")
    if not isinstance(entries_value, dict) or not entries_value:
        raise ValueError("spec.entries must be a non-empty object")

    spec_dir = spec_path.parent.resolve()
    manifest_entries: dict[str, UpdateManifestEntry] = {}
    for key, raw_entry in entries_value.items():
        if not isinstance(key, str):
            raise ValueError("spec.entries keys must be strings")
        if not isinstance(raw_entry, dict):
            raise ValueError(f"{key} entry must be a JSON object")
        manifest_entries[key] = build_entry(key, raw_entry, spec_dir)
    return UpdateManifest(entries=manifest_entries)


def main() -> None:
    args = parse_args()
    spec_path = Path(args.spec).resolve()
    output_path = Path(args.output).resolve()

    manifest = generate_manifest(spec_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as fp:
        json.dump(
            manifest.model_dump(mode="json")["entries"],
            fp,
            ensure_ascii=False,
            indent=None if args.compact else 2,
            separators=(",", ": ") if args.compact else None,
        )
        fp.write("\n")


if __name__ == "__main__":
    main()

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@contextmanager
def create_client(updater_rate_limit_per_minute: int = 30) -> Generator[TestClient, None, None]:
    app = create_app(
        Settings(
            updater_rate_limit_per_minute=updater_rate_limit_per_minute,
            update_manifest_path=str(Path("config/update_manifest.json.example")),
        )
    )
    with TestClient(app) as client:
        yield client


def test_latest_redirects_to_windows_download_url() -> None:
    with create_client() as client:
        response = client.get("/app/latest", params={"platform": "windows", "arch": "x64"}, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "https://download.example.com/OneTJSetup_2.3.0_12.exe"
    assert response.headers["x-request-id"]
    assert response.headers["cache-control"] == "no-store"


def test_latest_android_uses_default_arch_entry() -> None:
    with create_client() as client:
        response = client.get("/app/latest", params={"platform": "android"}, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "https://download.example.com/onetj-2.3.0-12.apk"


def test_latest_arch_is_case_insensitive_and_trimmed() -> None:
    with create_client() as client:
        response = client.get("/app/latest", params={"platform": "windows", "arch": " X64 "}, follow_redirects=False)
    assert response.status_code == 302


def test_latest_unknown_arch_is_rejected() -> None:
    with create_client() as client:
        response = client.get("/app/latest", params={"platform": "windows", "arch": "arm64"}, follow_redirects=False)
    assert response.status_code == 400
    assert response.json()["code"] == "BAD_REQUEST"
    assert response.json()["message"] == "unsupported platform or arch"


def test_latest_rate_limit_shares_updater_limit() -> None:
    with create_client(updater_rate_limit_per_minute=1) as client:
        first = client.get("/app/latest", params={"platform": "windows", "arch": "x64"}, follow_redirects=False)
        second = client.get("/app/latest", params={"platform": "windows", "arch": "x64"}, follow_redirects=False)
    assert first.status_code == 302
    assert second.status_code == 429
    assert second.json()["code"] == "RATE_LIMITED"

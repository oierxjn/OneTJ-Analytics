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


def test_has_update_when_version_is_lower() -> None:
    with create_client() as client:
        response = client.get(
            "/updater/v1/check",
            params={"platform": "windows", "arch": "x64", "current_version": "2.2.4", "current_build": "11"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["code"] == "SUCCESS"
    assert body["request_id"]
    assert body["data"]["has_update"] is True
    assert body["data"]["latest_version"] == "2.3.0"
    assert body["data"]["latest_build"] == 12


def test_has_update_when_build_is_lower() -> None:
    with create_client() as client:
        response = client.get(
            "/updater/v1/check",
            params={"platform": "windows", "arch": "x64", "current_version": "2.3.0", "current_build": "11"},
        )
    assert response.status_code == 200
    assert response.json()["data"]["has_update"] is True


def test_no_update_when_version_and_build_match() -> None:
    with create_client() as client:
        response = client.get(
            "/updater/v1/check",
            params={"platform": "windows", "arch": "x64", "current_version": "2.3.0", "current_build": "12"},
        )
    assert response.status_code == 200
    assert response.json()["data"] == {"has_update": False}


def test_android_uses_default_arch_entry() -> None:
    with create_client() as client:
        response = client.get(
            "/updater/v1/check",
            params={"platform": "android", "current_version": "2.2.4", "current_build": "11"},
        )
    assert response.status_code == 200
    assert response.json()["data"]["has_update"] is True


def test_invalid_version_is_rejected() -> None:
    with create_client() as client:
        response = client.get(
            "/updater/v1/check",
            params={"platform": "windows", "arch": "x64", "current_version": "2.3", "current_build": "11"},
        )
    assert response.status_code == 400
    assert response.json()["code"] == "BAD_REQUEST"
    assert "current_version" in response.json()["message"]


def test_invalid_build_is_rejected() -> None:
    with create_client() as client:
        response = client.get(
            "/updater/v1/check",
            params={"platform": "windows", "arch": "x64", "current_version": "2.3.0", "current_build": "0"},
        )
    assert response.status_code == 400
    assert response.json()["code"] == "BAD_REQUEST"
    assert "current_build" in response.json()["message"]


def test_unknown_platform_or_arch_is_rejected() -> None:
    with create_client() as client:
        response = client.get(
            "/updater/v1/check",
            params={"platform": "windows", "arch": "arm64", "current_version": "2.3.0", "current_build": "11"},
        )
    assert response.status_code == 400
    assert response.json()["code"] == "BAD_REQUEST"
    assert response.json()["message"] == "unsupported platform or arch"


def test_rate_limit_for_updater() -> None:
    with create_client(updater_rate_limit_per_minute=1) as client:
        first = client.get(
            "/updater/v1/check",
            params={"platform": "windows", "arch": "x64", "current_version": "2.2.4", "current_build": "11"},
        )
        second = client.get(
            "/updater/v1/check",
            params={"platform": "windows", "arch": "x64", "current_version": "2.2.4", "current_build": "11"},
        )
    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["code"] == "RATE_LIMITED"

from collections.abc import Generator
from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def build_payload() -> dict[str, str]:
    return {
        "hashId": "hash-2333333",
        "userid": "2333333",
        "username": "张三",
        "client_version": "1.2.3+45",
        "device_brand": "HUAWEI",
        "device_model": "Pura 70",
        "dept_name": "计算机科学与技术学院",
        "school_name": "同济大学",
        "gender": "男",
        "platform": "ohos",
    }


@contextmanager
def create_client(rate_limit_per_minute: int = 16) -> Generator[TestClient, None, None]:
    app = create_app(Settings(rate_limit_per_minute=rate_limit_per_minute))
    with TestClient(app) as client:
        yield client


def test_success() -> None:
    with create_client() as client:
        response = client.post("/collector/v1/events", json=build_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["code"] == "SUCCESS"
    assert body["message"] == "accepted"
    assert body["request_id"]


def test_omitted_field_is_allowed() -> None:
    with create_client() as client:
        payload = build_payload()
        payload.pop("userid")
        response = client.post("/collector/v1/events", json=payload)
    assert response.status_code == 200
    assert response.json()["code"] == "SUCCESS"


def test_missing_hash_id_is_rejected() -> None:
    with create_client() as client:
        response = client.post("/collector/v1/events", json={})
    assert response.status_code == 400
    assert response.json()["code"] == "BAD_REQUEST"


def test_non_string_field() -> None:
    with create_client() as client:
        payload = build_payload()
        payload["userid"] = 123  # type: ignore[assignment]
        response = client.post("/collector/v1/events", json=payload)
    assert response.status_code == 400
    assert response.json()["code"] == "BAD_REQUEST"


def test_blank_string_is_rejected() -> None:
    with create_client() as client:
        payload = build_payload()
        payload["userid"] = "   "
        response = client.post("/collector/v1/events", json=payload)
    assert response.status_code == 400
    assert response.json()["code"] == "BAD_REQUEST"
    assert response.json()["message"] == "field 'userid' must not be empty"


def test_blank_hash_id_is_rejected() -> None:
    with create_client() as client:
        payload = build_payload()
        payload["hashId"] = "   "
        response = client.post("/collector/v1/events", json=payload)
    assert response.status_code == 400
    assert response.json()["code"] == "BAD_REQUEST"
    assert response.json()["message"] == "field 'hashId' must not be empty"


def test_school_name_can_be_empty() -> None:
    with create_client() as client:
        payload = build_payload()
        payload["school_name"] = "   "
        response = client.post("/collector/v1/events", json=payload)
    assert response.status_code == 200
    assert response.json()["code"] == "SUCCESS"


def test_unsupported_media_type() -> None:
    with create_client() as client:
        response = client.post(
            "/collector/v1/events",
            content='{"userid":"2333333"}',
            headers={"content-type": "text/plain"},
        )
    assert response.status_code == 415
    assert response.json()["code"] == "UNSUPPORTED_MEDIA_TYPE"


def test_invalid_json() -> None:
    with create_client() as client:
        response = client.post(
            "/collector/v1/events",
            content='{"userid":',
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 400
    assert response.json()["code"] == "BAD_REQUEST"


def test_rate_limit() -> None:
    with create_client(rate_limit_per_minute=1) as client:
        first = client.post("/collector/v1/events", json=build_payload())
        second = client.post("/collector/v1/events", json=build_payload())
    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["code"] == "RATE_LIMITED"


def test_x_forwarded_for_priority() -> None:
    with create_client(rate_limit_per_minute=1) as client:
        headers1 = {"x-forwarded-for": "1.1.1.1, 2.2.2.2"}
        headers2 = {"x-forwarded-for": "3.3.3.3"}
        first = client.post("/collector/v1/events", json=build_payload(), headers=headers1)
        second = client.post("/collector/v1/events", json=build_payload(), headers=headers2)
    assert first.status_code == 200
    assert second.status_code == 200


def test_request_id_exists_on_error_and_success() -> None:
    with create_client(rate_limit_per_minute=1) as client:
        ok = client.post("/collector/v1/events", json=build_payload())
        limited = client.post("/collector/v1/events", json=build_payload())
    assert ok.json()["request_id"]
    assert limited.json()["request_id"]

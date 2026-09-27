import json
from datetime import UTC, datetime
from io import BytesIO
from urllib.error import HTTPError

import pytest

from kairos.adapters.openai_compatible import (
    ModelInvalidOutput,
    ModelUnavailable,
    OpenAICompatiblePlanner,
)


class FakeResponse:
    def __init__(self, body: dict[str, object]) -> None:
        self._body = json.dumps(body).encode()

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def test_planner_sends_context_and_validates_model_result(monkeypatch: pytest.MonkeyPatch) -> None:
    import kairos.adapters.openai_compatible as adapter

    captured: dict[str, object] = {}

    def fake_urlopen(request: object, timeout: float) -> FakeResponse:
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "status": "ready",
                                    "candidates": [
                                        {
                                            "title": "项目讨论",
                                            "timezone": "Asia/Shanghai",
                                            "start_at": "2026-09-26T14:00:00+08:00",
                                            "end_at": "2026-09-26T15:00:00+08:00",
                                        }
                                    ],
                                }
                            )
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(adapter, "urlopen", fake_urlopen)
    result = OpenAICompatiblePlanner("https://example.test/v1", "test-secret", "test-model").parse(
        "明天下午两点开会一小时",
        "Asia/Shanghai",
        datetime(2026, 9, 25, 2, tzinfo=UTC),
    )

    assert result.status == "ready"
    assert result.candidates[0].title == "项目讨论"
    assert captured["timeout"] == 20.0
    sent_request = captured["request"]
    assert sent_request.full_url.endswith("/chat/completions")
    assert sent_request.headers["Authorization"] == "Bearer test-secret"
    body = json.loads(sent_request.data)
    assert body["messages"][1]["content"].find("reference_now") >= 0


def test_planner_rejects_invalid_output_without_leaking_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import kairos.adapters.openai_compatible as adapter

    def fake_urlopen(request: object, timeout: float) -> FakeResponse:
        return FakeResponse(
            {"choices": [{"message": {"content": '{"status":"ready","unexpected":true}'}}]}
        )

    monkeypatch.setattr(adapter, "urlopen", fake_urlopen)
    planner = OpenAICompatiblePlanner("https://example.test/v1", "private-key", "test-model")

    with pytest.raises(ModelInvalidOutput) as error:
        planner.parse("测试", "Asia/Shanghai", datetime.now(UTC))
    assert "private-key" not in str(error.value)


def test_planner_maps_http_error_without_provider_body(monkeypatch: pytest.MonkeyPatch) -> None:
    import kairos.adapters.openai_compatible as adapter

    def fake_urlopen(request: object, timeout: float) -> FakeResponse:
        raise HTTPError(
            "https://example.test/v1/chat/completions", 401, "unauthorized", {}, BytesIO(b"secret")
        )

    monkeypatch.setattr(adapter, "urlopen", fake_urlopen)
    planner = OpenAICompatiblePlanner("https://example.test/v1", "private-key", "test-model")

    with pytest.raises(ModelUnavailable) as error:
        planner.parse("测试", "Asia/Shanghai", datetime.now(UTC))
    assert "secret" not in str(error.value)
    assert "private-key" not in str(error.value)

import json
from urllib.error import HTTPError

import pytest

from kairos.adapters.ai.assistant_model import MimoToolModel
from kairos.adapters.ai.mimo import MimoError


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        if isinstance(self.payload, bytes):
            return self.payload
        return json.dumps(self.payload, ensure_ascii=False).encode()


def test_adapter_sends_tool_schemas_and_decodes_calls_without_executing(monkeypatch):
    captured = {}
    payload = {"choices": [{"message": {"role": "assistant", "content": "", "reasoning_content": "meta",
        "tool_calls": [{"id": "tc-1", "type": "function", "function": {
            "name": "query_flexible_tasks", "arguments": "{}"}}]}}]}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data)
        captured["auth"] = request.get_header("Authorization")
        captured["timeout"] = timeout
        return FakeResponse(payload)

    monkeypatch.setattr("kairos.adapters.ai.assistant_model.urlopen", fake_urlopen)
    adapter = MimoToolModel("secret-key", base_url="https://api.xiaomimimo.com/v1/",
                            model="mimo-v2.6-pro")
    result = adapter.complete([{"role": "user", "content": "列出我的任务"}], [
        {"type": "function", "function": {"name": "query_flexible_tasks"}}
    ])

    assert captured["url"] == "https://api.xiaomimimo.com/v1/chat/completions"
    assert captured["auth"] == "Bearer secret-key"
    assert captured["body"]["tools"][0]["function"]["name"] == "query_flexible_tasks"
    assert captured["body"]["tool_choice"] == "auto"
    assert result.tool_calls[0].call_id == "tc-1"
    assert result.tool_calls[0].arguments_json == "{}"
    assert result.reasoning_content == "meta"
    assert result.provider_message["tool_calls"] == payload["choices"][0]["message"]["tool_calls"]


def test_adapter_transports_current_turn_multimodal_content_parts(monkeypatch):
    captured = {}
    monkeypatch.setattr("kairos.adapters.ai.assistant_model.urlopen", lambda request, timeout: (
        captured.update(body=json.loads(request.data), timeout=timeout) or FakeResponse(
            {"choices": [{"message": {"content": "已分析图片"}}]})))
    adapter = MimoToolModel("secret-key", base_url="https://provider.invalid/v1", model="mimo-v2.6-pro")
    content = [
        {"type": "text", "text": "KAIROS_IMAGE_JSON_EXTRACTION 请分析课表"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,aGVsbG8="}},
    ]
    adapter.complete([{"role": "user", "content": content}], [])
    assert captured["body"]["messages"][0]["content"] == content
    assert captured["body"]["max_completion_tokens"] == 4096
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["timeout"] == 60
    assert "secret-key" not in json.dumps(captured["body"])


def test_adapter_keeps_text_turn_budget_unchanged(monkeypatch):
    captured = {}
    monkeypatch.setattr("kairos.adapters.ai.assistant_model.urlopen", lambda request, timeout: (
        captured.update(body=json.loads(request.data), timeout=timeout) or FakeResponse(
            {"choices": [{"message": {"content": "ok"}}]})))
    adapter = MimoToolModel("secret-key", base_url="https://provider.invalid/v1", model="mimo-v2.6-pro")
    adapter.complete([{"role": "user", "content": "你好"}], [])
    assert captured["body"]["max_completion_tokens"] == 1024
    assert "response_format" not in captured["body"]
    assert captured["timeout"] == 30


def test_general_image_query_uses_multimodal_transport_without_json_forcing(monkeypatch):
    captured = {}
    monkeypatch.setattr("kairos.adapters.ai.assistant_model.urlopen", lambda request, timeout: (
        captured.update(body=json.loads(request.data), timeout=timeout) or FakeResponse(
            {"choices": [{"message": {"content": "图中是一只鸟。"}}]})))
    adapter = MimoToolModel("secret-key", base_url="https://provider.invalid/v1", model="mimo-v2.6-pro")
    content = [
        {"type": "text", "text": "请描述图片"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,aGVsbG8="}},
    ]
    result = adapter.complete([{"role": "user", "content": content}], [])
    assert result.text == "图中是一只鸟。"
    assert "response_format" not in captured["body"]
    assert captured["body"]["max_completion_tokens"] == 4096
    assert captured["timeout"] == 60


@pytest.mark.parametrize("payload", [
    {"choices": [{"message": {"content": None, "tool_calls": [{"type": "function", "function": {
        "name": "create_flexible_task", "arguments": "{}"}}]}}]},
    {"choices": [{"message": {"content": "", "tool_calls": [{"id": "x", "function": {
        "name": "create_flexible_task", "arguments": "{"}}]}}]},
    {"choices": [{"message": {"content": "", "tool_calls": "invalid"}}]},
    b"not json",
])
def test_malformed_provider_responses_raise_sanitized_error(monkeypatch, payload):
    monkeypatch.setattr("kairos.adapters.ai.assistant_model.urlopen",
                        lambda *_args, **_kwargs: FakeResponse(payload))
    adapter = MimoToolModel("secret-key", base_url="https://provider.invalid/v1", model="test")

    with pytest.raises(MimoError) as error:
        adapter.complete([], [])

    assert "secret-key" not in str(error.value)
    assert "not json" not in str(error.value)


def test_provider_http_body_is_not_leaked(monkeypatch):
    def fail(*_args, **_kwargs):
        raise HTTPError("https://provider.invalid", 401, "denied secret", {}, None)

    monkeypatch.setattr("kairos.adapters.ai.assistant_model.urlopen", fail)
    adapter = MimoToolModel("secret-key", base_url="https://provider.invalid/v1", model="test")

    with pytest.raises(MimoError) as error:
        adapter.complete([], [])

    assert str(error.value) == "MiMo returned HTTP 401"
    assert "secret" not in str(error.value)

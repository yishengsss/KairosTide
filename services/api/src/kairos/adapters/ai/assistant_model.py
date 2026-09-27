"""MiMo OpenAI-compatible tool-call transport; it never executes tools."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from kairos.adapters.ai.mimo import MimoError
from kairos.application.assistant_tasks import ModelTurn, ToolCall


class MimoToolModel:
    def __init__(self, api_key: str, *, base_url: str, model: str,
                 timeout: float = 30, max_completion_tokens: int = 1024) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_completion_tokens = max_completion_tokens

    def complete(self, messages: list[dict], tools: list[dict]) -> ModelTurn:
        has_image = any(
            isinstance(message.get("content"), list)
            and any(isinstance(part, dict) and part.get("type") in {"image_url", "input_image"}
                    for part in message["content"])
            for message in messages if isinstance(message, dict)
        )
        structured_image = has_image and any(
            isinstance(part, dict) and part.get("type") == "text"
            and isinstance(part.get("text"), str)
            and "KAIROS_IMAGE_JSON_EXTRACTION" in part["text"]
            for message in messages if isinstance(message, dict) and isinstance(message.get("content"), list)
            for part in message["content"]
        )
        completion_tokens = max(self.max_completion_tokens, 4096) if has_image else self.max_completion_tokens
        request_timeout = max(self.timeout, 60) if has_image else self.timeout
        body = json.dumps({
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "max_completion_tokens": completion_tokens,
            "stream": False,
            **({"response_format": {"type": "json_object"}} if structured_image else {}),
        }, ensure_ascii=False).encode("utf-8")
        request = Request(
            f"{self.base_url}/chat/completions", data=body,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=request_timeout) as response:
                payload = json.loads(response.read())
        except HTTPError as exc:
            raise MimoError(f"MiMo returned HTTP {exc.code}") from None
        except (URLError, TimeoutError, OSError):
            raise MimoError("MiMo request failed") from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise MimoError("MiMo returned an invalid response") from None

        try:
            message = payload["choices"][0]["message"]
            text = message.get("content")
            reasoning = message.get("reasoning_content")
            raw_calls = message.get("tool_calls") or []
        except (KeyError, IndexError, TypeError, AttributeError):
            raise MimoError("MiMo response did not contain a valid message") from None
        if text is not None and not isinstance(text, str):
            raise MimoError("MiMo response contained invalid content")
        if reasoning is not None and not isinstance(reasoning, str):
            raise MimoError("MiMo response contained invalid reasoning metadata")
        if not isinstance(raw_calls, list) or len(raw_calls) > 8:
            raise MimoError("MiMo response contained invalid tool calls")

        calls: list[ToolCall] = []
        try:
            for item in raw_calls:
                function = item["function"]
                arguments = function["arguments"]
                if not isinstance(arguments, str) or not isinstance(json.loads(arguments), dict):
                    raise ValueError("arguments must be a JSON object")
                calls.append(ToolCall(
                    call_id=item["id"], name=function["name"],
                    arguments_json=arguments,
                ))
        except (KeyError, TypeError, ValueError):
            raise MimoError("MiMo returned a malformed tool call") from None
        provider_message = {"role": "assistant", "content": text or "", "tool_calls": raw_calls}
        if reasoning is not None:
            provider_message["reasoning_content"] = reasoning
        return ModelTurn(text=text, tool_calls=tuple(calls), reasoning_content=reasoning,
                         provider_message=provider_message)

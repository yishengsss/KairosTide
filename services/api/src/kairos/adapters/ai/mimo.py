"""Minimal server-side Xiaomi MiMo chat completion client."""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class MimoError(RuntimeError):
    """Provider request failed; deliberately excludes credentials and body text."""


class MimoClient:
    def __init__(self, api_key: str, *, base_url: str, model: str, timeout: float = 30) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    @classmethod
    def from_environment(cls) -> "MimoClient | None":
        api_key = os.environ.get("MIMO_API_KEY", "").strip()
        if not api_key:
            return None
        return cls(
            api_key,
            base_url=os.environ.get("MIMO_BASE_URL", "https://api.xiaomimimo.com/v1"),
            model=os.environ.get("MIMO_MODEL", "mimo-v2.6-pro"),
        )

    def reply(self, messages: list[dict[str, str]]) -> str:
        payload = json.dumps({
            "model": self.model,
            "messages": [{"role": "system", "content": _SYSTEM_PROMPT}, *messages],
            "max_completion_tokens": 1024,
            "stream": False,
        }).encode("utf-8")
        request = Request(
            f"{self.base_url}/chat/completions",
            data=payload,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read())
        except HTTPError as exc:
            raise MimoError(f"MiMo returned HTTP {exc.code}") from None
        except (URLError, TimeoutError, OSError):
            raise MimoError("MiMo request failed") from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise MimoError("MiMo returned an invalid response") from None

        try:
            answer = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise MimoError("MiMo response did not contain an answer") from None
        if not isinstance(answer, str) or not answer.strip():
            raise MimoError("MiMo returned an empty answer")
        return answer.strip()


_SYSTEM_PROMPT = """你是 Kairos 助手。Kairos 尊重用户自主安排，不主动要求用户开始任务。
你只能回答对话问题；当前版本没有连接事件、柔性任务、天气等写入或查询工具。
不得声称已创建、保存、修改、删除、请假或查询任何安排/任务；如果用户提出这些操作，坦诚说明当前尚未接通对应能力。
不得虚构用户的日程、任务、地点或天气。回答简洁、自然，使用用户当前使用的语言。"""

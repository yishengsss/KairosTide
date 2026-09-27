"""Durable assistant conversation orchestration and bounded model context."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import Any

from kairos.application.assistant_tasks import AssistantService
from kairos.application.image_input import ValidatedImage
from kairos.domain.conversations import (
    ConversationConflict,
    ConversationMessageRecord,
    ConversationNotFound,
    ConversationPage,
    ConversationRecord,
    ConversationTurn,
)

MAX_CONTEXT_MESSAGES = 24
MAX_CONTEXT_CHARS = 32_000
_EXACT_CONFIRMATION = re.compile(
    r"^(?:确认保存全部项目|确认保存|确认|保存日程|保存)[。！!\s]*$")


class ContextTooLarge(ValueError):
    """The newest user turn cannot fit within the model's bounded context."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, dict):
        return {str(key): _plain(nested) for key, nested in value.items() if key != "owner_id"}
    if isinstance(value, (list, tuple)):
        return [_plain(nested) for nested in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _message_response(turn: ConversationTurn) -> dict[str, Any]:
    def convert(record: ConversationMessageRecord | None):
        if record is None:
            return None
        return {
            "message_id": record.message_id,
            "sequence": record.sequence,
            "role": record.role,
            "content": record.content,
            "created_at": record.created_at,
            "status": record.status,
            "action_results": record.action_results,
            "draft_refs": record.draft_refs,
        }

    return {
        "user_message": convert(turn.user_message),
        "answer": convert(turn.assistant_message),
        "status": turn.status,
        "tool_results": turn.action_results,
        "draft_refs": turn.draft_refs,
        "revision": turn.revision,
    }


class ConversationService:
    def __init__(self, repository, assistant: AssistantService | None) -> None:
        self.repository = repository
        self.assistant = assistant

    def create(self, owner_id: str, idempotency_key: str) -> ConversationRecord:
        if not idempotency_key.strip():
            raise ValueError("Idempotency-Key is required")
        return self.repository.create_conversation(owner_id, idempotency_key, _json_hash({"create": True}))

    def read(self, owner_id: str, conversation_id: str, after_sequence: int = 0,
             limit: int = 100) -> ConversationPage:
        return self.repository.list_conversation_messages(owner_id, conversation_id, after_sequence, limit)

    def append_turn(self, owner_id: str, conversation_id: str, client_message_id: str,
                    content: str, timezone: str, expected_sequence: int,
                    image: ValidatedImage | None = None) -> dict[str, Any]:
        if not client_message_id or len(client_message_id) > 200:
            raise ValueError("invalid client message ID")
        if not content.strip():
            raise ValueError("message content must not be blank")
        request_hash = _json_hash({
            "content": content,
            "timezone": timezone,
            "expected_sequence": expected_sequence,
            "image_sha256": image.sha256 if image else None,
        })
        turn = self.repository.reserve_conversation_turn(owner_id, conversation_id, client_message_id,
            content, timezone, expected_sequence, request_hash)
        if turn.status == "completed":
            return _message_response(turn)

        if image is None and _EXACT_CONFIRMATION.fullmatch(content.strip()):
            draft_id = self._latest_confirmable_draft_ref(owner_id, conversation_id)
            draft = self.repository.get_draft(owner_id, draft_id) if draft_id else None
            if draft is not None and draft.status == "committed":
                results = [{"action": "confirm_rigid_event_draft", "status": "succeeded",
                            "data": {"draft_id": draft.draft_id}, "message": None}]
                completed = self.repository.complete_conversation_turn(owner_id, conversation_id,
                    client_message_id, "已保存这份日程。", results, [draft.draft_id])
                return _message_response(completed)

        if self.assistant is None:
            raise RuntimeError("assistant is not configured")

        messages = self._history_for_context(owner_id, conversation_id,
                                             turn.user_message.sequence)
        context = self.build_model_context(messages, turn.user_message.message_id)
        result = self.assistant.handle(owner_id, client_message_id, timezone, context, image=image)
        action_results = [{
            "action": item.action,
            "status": item.status,
            "data": _plain(item.data),
            "message": item.message,
        } for item in result.action_results if not item.internal]
        draft_refs = []
        if result.draft is not None:
            draft_id = getattr(result.draft, "draft_id", None)
            if draft_id:
                draft_refs.append(draft_id)
        for action in action_results:
            data = action.get("data")
            if isinstance(data, dict) and isinstance(data.get("draft_id"), str):
                draft_refs.append(data["draft_id"])
        draft_refs = list(dict.fromkeys(draft_refs))
        completed = self.repository.complete_conversation_turn(owner_id, conversation_id,
            client_message_id, result.answer, action_results, draft_refs)
        return _message_response(completed)

    def _latest_confirmable_draft_ref(self, owner_id: str, conversation_id: str) -> str | None:
        latest_assistant: ConversationMessageRecord | None = None
        cursor = 0
        while True:
            page = self.repository.list_conversation_messages(owner_id, conversation_id, cursor, 250)
            for message in page.items:
                if message.role == "assistant":
                    latest_assistant = message
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
        if (latest_assistant is None or not latest_assistant.draft_refs
                or not re.search(r"确认|核对", latest_assistant.content)):
            return None
        if any(result.get("action") == "confirm_rigid_event_draft"
               for result in latest_assistant.action_results):
            return None
        return latest_assistant.draft_refs[-1]

    def _history_for_context(self, owner_id: str, conversation_id: str,
                             latest_sequence: int) -> list[ConversationMessageRecord]:
        # Keep storage/history size independent from model context work. The
        # extra record allows the builder to align its first candidate pair.
        after_sequence = max(0, latest_sequence - (MAX_CONTEXT_MESSAGES + 1))
        page = self.repository.list_conversation_messages(owner_id, conversation_id,
                                                           after_sequence, MAX_CONTEXT_MESSAGES + 1)
        return page.items

    @staticmethod
    def build_model_context(messages: list[ConversationMessageRecord],
                            latest_user_message_id: str) -> list[dict[str, str]]:
        latest_index = next((index for index in range(len(messages) - 1, -1, -1)
                             if messages[index].message_id == latest_user_message_id), None)
        if latest_index is None or messages[latest_index].role != "user":
            raise ValueError("latest user turn is missing from conversation history")
        latest = messages[latest_index]
        if len(latest.content) > MAX_CONTEXT_CHARS:
            raise ContextTooLarge("latest user message exceeds the model context limit")
        selected = [latest]
        char_count = len(latest.content)
        index = latest_index - 1
        while index >= 1 and len(selected) + 2 <= MAX_CONTEXT_MESSAGES:
            assistant = messages[index]
            user = messages[index - 1]
            if not (user.role == "user" and assistant.role == "assistant"
                    and user.status == "completed" and assistant.status == "completed"):
                break
            turn_chars = len(user.content) + len(assistant.content)
            if char_count + turn_chars > MAX_CONTEXT_CHARS:
                break
            selected[0:0] = [user, assistant]
            char_count += turn_chars
            index -= 2
        return [{"role": item.role, "content": item.content} for item in selected]


def _json_hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()

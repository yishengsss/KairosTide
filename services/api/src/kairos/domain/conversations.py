"""Pure records and conflicts for durable assistant conversations."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


class ConversationNotFound(Exception):
    """The conversation does not belong to the requesting owner."""


class ConversationConflict(Exception):
    def __init__(self, message: str, *, current_sequence: int | None = None,
                 current_revision: int | None = None) -> None:
        super().__init__(message)
        self.current_sequence = current_sequence
        self.current_revision = current_revision


@dataclass(frozen=True)
class ConversationRecord:
    conversation_id: str
    owner_id: str
    revision: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ConversationMessageRecord:
    message_id: str
    conversation_id: str
    sequence: int
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime
    status: Literal["pending", "completed"]
    action_results: list[dict]
    draft_refs: list[str]


@dataclass(frozen=True)
class ConversationTurn:
    conversation_id: str
    client_message_id: str
    user_message: ConversationMessageRecord
    assistant_message: ConversationMessageRecord | None
    status: Literal["pending", "completed"]
    action_results: list[dict]
    draft_refs: list[str]
    revision: int


@dataclass(frozen=True)
class ConversationPage:
    items: list[ConversationMessageRecord]
    next_cursor: int | None
    revision: int
    draft_refs: list[str]

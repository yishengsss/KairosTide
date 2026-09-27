"""Facts and validation for user-authored flexible tasks."""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Literal


DeadlinePrecision = Literal["date", "instant"] | None
TaskLifecycleStatus = Literal["planned", "active", "completed"]


class TaskNotFound(KeyError):
    """No task with the exact requested title belongs to this owner."""


class AmbiguousTaskTitle(ValueError):
    """More than one owner's task has the requested normalized title."""


class IdempotencyConflict(ValueError):
    """An idempotency key was reused for a different operation payload."""


class TaskVersionConflict(ValueError):
    """The task changed since the caller last read it."""


class InvalidTaskTransition(ValueError):
    """The requested lifecycle change is not allowed."""


def validate_task_transition(current: TaskLifecycleStatus, target: TaskLifecycleStatus) -> None:
    if (current, target) not in {
        ("planned", "active"), ("active", "planned"), ("active", "completed"),
    }:
        raise InvalidTaskTransition(f"cannot transition task from {current} to {target}")


@dataclass(frozen=True)
class FlexibleTaskRecord:
    task_id: str
    owner_id: str
    version: int
    title: str
    deadline: date | datetime | None
    deadline_precision: DeadlinePrecision
    timezone: str
    source_message_id: str | None
    lifecycle_status: TaskLifecycleStatus = "planned"

    def __post_init__(self) -> None:
        if not self.task_id or not self.owner_id or self.version < 1:
            raise ValueError("task identity and positive version are required")
        if not self.title or not self.title.strip():
            raise ValueError("task title is required")
        if not self.timezone:
            raise ValueError("task timezone is required")
        if self.lifecycle_status not in ("planned", "active", "completed"):
            raise ValueError("unsupported task lifecycle status")
        if self.deadline_precision is None:
            if self.deadline is not None:
                raise ValueError("deadline precision is required when a deadline is set")
        elif self.deadline_precision == "date":
            if not isinstance(self.deadline, date) or isinstance(self.deadline, datetime):
                raise ValueError("date precision requires a date deadline")
        elif self.deadline_precision == "instant":
            if not isinstance(self.deadline, datetime) or self.deadline.tzinfo is None:
                raise ValueError("instant precision requires a timezone-aware datetime")
            object.__setattr__(self, "deadline", self.deadline.astimezone(timezone.utc))
        else:
            raise ValueError("unsupported deadline precision")


def normalized_title(title: str) -> str:
    """Compare exact titles without case sensitivity; preserve original facts."""
    return title.casefold()

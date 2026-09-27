"""Owner-scoped use cases for explicitly managed flexible tasks."""

from datetime import date, datetime
from typing import Protocol

from kairos.domain.tasks import FlexibleTaskRecord, TaskLifecycleStatus


class TaskStore(Protocol):
    def create_flexible_task(self, record: FlexibleTaskRecord, idempotency_key: str,
                             request_hash: str) -> FlexibleTaskRecord: ...

    def list_flexible_tasks(self, owner_id: str) -> list[FlexibleTaskRecord]: ...

    def update_flexible_task_by_title(self, owner_id: str, title: str, changes: dict,
                                      source_message_id: str | None, idempotency_key: str,
                                      request_hash: str) -> FlexibleTaskRecord: ...

    def delete_flexible_task_by_title(self, owner_id: str, title: str, source_message_id: str | None,
                                      idempotency_key: str, request_hash: str) -> FlexibleTaskRecord: ...

    def transition_flexible_task(self, owner_id: str, task_id: str, target: TaskLifecycleStatus,
                                 expected_version: int, idempotency_key: str,
                                 request_hash: str) -> FlexibleTaskRecord: ...


class FlexibleTaskService:
    def __init__(self, store: TaskStore) -> None:
        self.store = store

    @staticmethod
    def _hash(payload: list) -> str:
        import hashlib
        import json

        def encode_value(value):
            if isinstance(value, (date, datetime)):
                return value.isoformat()
            raise TypeError(f"unsupported idempotency payload value: {type(value).__name__}")

        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":"),
                                         default=encode_value).encode()).hexdigest()

    def create(self, owner_id: str, title: str, deadline: date | datetime | None,
               deadline_precision: str | None, timezone: str, source_message_id: str | None,
               idempotency_key: str) -> FlexibleTaskRecord:
        import uuid
        payload = [title, deadline.isoformat() if deadline else None, deadline_precision,
                   timezone, source_message_id]
        record = FlexibleTaskRecord(f"task_{uuid.uuid4().hex}", owner_id, 1, title, deadline,
                                    deadline_precision, timezone, source_message_id)
        return self.store.create_flexible_task(record, idempotency_key, self._hash(payload))

    def list(self, owner_id: str) -> list[FlexibleTaskRecord]:
        return self.store.list_flexible_tasks(owner_id)

    def transition(self, owner_id: str, task_id: str, target: TaskLifecycleStatus,
                   expected_version: int, idempotency_key: str) -> FlexibleTaskRecord:
        return self.store.transition_flexible_task(owner_id, task_id, target, expected_version,
            idempotency_key, self._hash([task_id, target, expected_version]))

    def update_by_title(self, owner_id: str, title: str, changes: dict,
                        source_message_id: str | None, idempotency_key: str) -> FlexibleTaskRecord:
        allowed = {"title", "deadline", "deadline_precision", "timezone"}
        if not changes or set(changes) - allowed:
            raise ValueError("task update contains unsupported fields")
        payload = [title, changes, source_message_id]
        return self.store.update_flexible_task_by_title(owner_id, title, changes, source_message_id,
                                                        idempotency_key, self._hash(payload))

    def delete_by_title(self, owner_id: str, title: str, source_message_id: str | None,
                        idempotency_key: str) -> FlexibleTaskRecord:
        payload = [title, source_message_id]
        return self.store.delete_flexible_task_by_title(owner_id, title, source_message_id,
                                                        idempotency_key, self._hash(payload))

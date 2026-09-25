class DatabaseNotInitialized(Exception):
    """Raised when an explicit database initialization has not been run."""


class RecurrenceNeedsDSTPolicy(Exception):
    """Raised when a recurring wall-clock time needs an explicit DST choice."""


class OccurrenceNotFound(Exception):
    """Raised when an occurrence identifier does not match a real event."""


class ExceptionConflict(Exception):
    """Raised when an occurrence already has a different exception."""


class EventNotFound(Exception):
    """Raised when an event series does not exist."""


class EventVersionConflict(Exception):
    """Raised when a mutation uses a stale event version."""


class SeriesHasExceptions(Exception):
    """Raised when changing recurrence data would invalidate existing exceptions."""


class DraftNotFound(Exception):
    """Raised when a persisted planning draft does not exist."""


class DraftVersionConflict(Exception):
    """Raised when a draft is stale or cannot be committed in its current state."""


class IdempotencyKeyReused(Exception):
    """Raised when an idempotency key is reused for a different commit request."""

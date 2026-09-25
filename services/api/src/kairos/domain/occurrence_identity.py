"""Identity is an opaque registered ID, keyed by an immutable original slot."""

from uuid import NAMESPACE_URL, uuid5


def new_occurrence_id(event_id: str, original_slot: str) -> str:
    if not event_id or not original_slot:
        raise ValueError("event and immutable slot required")
    return f"occ_{uuid5(NAMESPACE_URL, f'kairos/{event_id}/{original_slot}').hex}"

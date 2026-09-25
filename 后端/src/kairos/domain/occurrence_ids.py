import base64
import binascii


def make_occurrence_id(event_id: str, occurrence_key: str) -> str:
    payload = f"{event_id}\0{occurrence_key}".encode()
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def parse_occurrence_id(occurrence_id: str) -> tuple[str, str]:
    padded = occurrence_id + "=" * (-len(occurrence_id) % 4)
    try:
        payload = base64.b64decode(padded, altchars=b"-_", validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as error:
        raise ValueError("invalid occurrence id") from error
    if "\0" not in payload:
        raise ValueError("invalid occurrence id")
    event_id, occurrence_key = payload.split("\0", 1)
    if not event_id or not occurrence_key:
        raise ValueError("invalid occurrence id")
    return event_id, occurrence_key

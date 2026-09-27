"""Reviewable rigid-event edits and deletion; confirmation is a separate command."""

from datetime import datetime


def normalized_changes(action: str, scope: str, changes: dict | None) -> dict:
    if scope not in ("occurrence", "series") or action not in ("update", "delete"):
        raise ValueError("explicit scope and supported action are required")
    if action == "delete":
        if changes:
            raise ValueError("delete proposals cannot contain edits")
        return {}
    if not changes or set(changes) - {"title", "location", "start_at", "end_at"}:
        raise ValueError("supported edits are title, location, start_at, end_at")
    if scope == "series" and set(changes) & {"start_at", "end_at"}:
        raise ValueError("series schedule remapping is not supported; edit one occurrence or change the series details")
    if ("start_at" in changes) != ("end_at" in changes):
        raise ValueError("start_at and end_at must be changed together")
    if "title" in changes and (not isinstance(changes["title"], str) or not changes["title"].strip()):
        raise ValueError("title must be nonempty")
    if "location" in changes and changes["location"] is not None and not isinstance(changes["location"], str):
        raise ValueError("location must be text or null")
    result = dict(changes)
    for key in ("start_at", "end_at"):
        if key in result:
            if not isinstance(result[key], str):
                raise ValueError(f"{key} must be an ISO timestamp")
            value = datetime.fromisoformat(result[key])
            if value.tzinfo is None:
                raise ValueError(f"{key} must include a timezone offset")
            result[key] = value.isoformat()
    if "start_at" in result:
        if datetime.fromisoformat(result["end_at"]) <= datetime.fromisoformat(result["start_at"]):
            raise ValueError("end_at must follow start_at")
    return result

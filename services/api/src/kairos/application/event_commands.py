"""Series edits need an explicit reviewed scope; unsupported transforms are refused."""


class UnsupportedEditScope(ValueError):
    code = "UNSUPPORTED_EDIT_SCOPE"


def require_supported_edit_scope(scope: str, *, changes_recurrence: bool) -> None:
    if scope not in ("occurrence", "series"):
        raise ValueError("edit scope must be explicit")
    if scope == "series" and changes_recurrence:
        raise UnsupportedEditScope("series slot remapping is not implemented")

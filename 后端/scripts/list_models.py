import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main() -> int:
    base_url = os.getenv("KAIROS_AI_BASE_URL", "").rstrip("/")
    api_key = os.getenv("KAIROS_AI_API_KEY", "")
    if not base_url or not api_key:
        print("Set KAIROS_AI_BASE_URL and KAIROS_AI_API_KEY in this shell first.", file=sys.stderr)
        return 2
    request = Request(
        f"{base_url}/models",
        headers={"Authorization": f"Bearer {api_key}"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=10) as response:
            body = json.loads(response.read())
    except HTTPError as error:
        print(
            f"Model listing failed with HTTP {error.code}; response body suppressed.",
            file=sys.stderr,
        )
        return 1
    except (TimeoutError, URLError, OSError, json.JSONDecodeError):
        print(
            "Model listing failed; network or response error (details suppressed).",
            file=sys.stderr,
        )
        return 1
    model_ids = sorted(
        item["id"]
        for item in body.get("data", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    )
    if not model_ids:
        print(
            "No model IDs were returned in the expected OpenAI-compatible format.",
            file=sys.stderr,
        )
        return 1
    print("\n".join(model_ids))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

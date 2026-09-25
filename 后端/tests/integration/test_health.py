import asyncio

from httpx import ASGITransport, AsyncClient

from kairos.main import app


def test_health_without_ai_credentials() -> None:
    async def request_health() -> tuple[int, dict[str, str]]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health")
        return response.status_code, response.json()

    status_code, body = asyncio.run(request_health())

    assert status_code == 200
    assert body == {"status": "ok"}

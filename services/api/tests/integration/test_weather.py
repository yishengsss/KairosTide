from datetime import UTC, datetime

from fastapi.testclient import TestClient

from kairos.application.weather import (
    WeatherLocation,
    WeatherLocationAmbiguous,
    WeatherLocationChoice,
    WeatherObservation,
    WeatherResult,
)
from kairos.main import create_app


class Clock:
    def now(self):
        return datetime(2026, 9, 26, 10, tzinfo=UTC)


class Provider:
    source = "Open-Meteo"
    attribution = "Weather data by Open-Meteo (CC BY 4.0)"

    def __init__(self, *, ambiguous=False, fail=False):
        self.ambiguous = ambiguous
        self.fail = fail
        self.queries = []

    def current(self, city):
        self.queries.append((city, None, None))
        if self.ambiguous:
            raise WeatherLocationAmbiguous(city, (
                WeatherLocationChoice("Springfield", 1, 2, "UTC", "A"),
                WeatherLocationChoice("Springfield", 3, 4, "UTC", "B"),
            ))
        if self.fail:
            raise OSError("offline")
        location = WeatherLocation("上海", 31.23, 121.47, "Asia/Shanghai", "中国")
        return WeatherResult("available", location, self.source,
            datetime(2026, 9, 26, 10, tzinfo=UTC),
            (WeatherObservation("rain", 95, 0.4, 5000, datetime(2026, 9, 26, 9, 30, tzinfo=UTC),
                                datetime(2026, 9, 26, 10, 30, tzinfo=UTC)),), self.attribution)

    def forecast(self, city, from_at, to_at):
        self.queries.append((city, from_at, to_at))
        return self.current(city)


def test_weather_route_requires_explicit_city_and_returns_attributed_current_facts():
    provider = Provider()
    with TestClient(create_app(clock=Clock(), owner_id="local", weather_provider=provider)) as client:
        response = client.get("/api/v1/weather", params={"location_id": "上海"})

    assert response.status_code == 200
    body = response.json()
    assert body["availability"] == "available"
    assert body["location_label"] == "上海, 中国"
    assert body["source"] == "Open-Meteo"
    assert body["attribution"] == "Weather data by Open-Meteo (CC BY 4.0)"
    assert body["observations"][0]["kind"] == "current"
    assert body["observations"][0]["condition"] == "rain"
    assert provider.queries == [("上海", None, None)]


def test_ambiguous_weather_city_returns_choices_instead_of_selecting_a_match():
    provider = Provider(ambiguous=True)
    with TestClient(create_app(clock=Clock(), owner_id="local", weather_provider=provider)) as client:
        response = client.get("/api/v1/weather", params={"location_id": "Springfield"})

    assert response.status_code == 200
    body = response.json()
    assert body["availability"] == "unavailable"
    assert len(body["location_choices"]) == 2
    assert body["observations"] == []


def test_weather_failure_is_unavailable_without_claiming_clear_conditions():
    with TestClient(create_app(clock=Clock(), owner_id="local", weather_provider=Provider(fail=True))) as client:
        response = client.get("/api/v1/weather", params={"location_id": "上海"})

    assert response.status_code == 200
    body = response.json()
    assert body["availability"] == "unavailable"
    assert body["observations"] == []
    assert body["detail"]


def test_weather_requires_location_and_does_not_keep_a_default_city():
    provider = Provider()
    with TestClient(create_app(clock=Clock(), owner_id="local", weather_provider=provider)) as client:
        missing = client.get("/api/v1/weather")
        blank = client.get("/api/v1/weather", params={"location_id": " "})

    assert missing.status_code == 422
    assert blank.status_code == 422
    assert provider.queries == []

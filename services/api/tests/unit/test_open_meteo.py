from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from kairos.adapters.weather.open_meteo import OpenMeteoWeatherProvider
from kairos.application.weather import WeatherLocationAmbiguous, WeatherLocationChoice, WeatherService


class FakeTransport:
    def __init__(self, replies):
        self.replies = replies
        self.urls = []

    def get_json(self, url, *, timeout):
        self.urls.append((url, timeout))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def geocoded(*, name="Paris", latitude=48.8566, longitude=2.3522, **extra):
    return {"results": [{"id": 1, "name": name, "latitude": latitude, "longitude": longitude,
                         "timezone": "Europe/Paris", "country": "France", **extra}]}


def test_explicit_city_resolves_to_current_observation_with_source_and_freshness():
    transport = FakeTransport([
        geocoded(),
        {"timezone": "Europe/Paris", "current": {"time": "2026-09-26T12:00", "temperature_2m": 21.5,
         "weather_code": 3, "cloud_cover": 68, "precipitation": 0.0, "visibility": 24000}},
    ])
    provider = OpenMeteoWeatherProvider(transport=transport)
    service = WeatherService(provider, clock=lambda: datetime(2026, 9, 26, 10, 1, tzinfo=UTC))

    result = service.query("Paris")

    assert result.availability == "available"
    assert result.location.name == "Paris"
    assert result.source == "Open-Meteo"
    assert result.fetched_at == datetime(2026, 9, 26, 10, 1, tzinfo=UTC)
    assert result.observations[0].condition == "overcast"
    assert result.observations[0].observed_at == datetime(2026, 9, 26, 10, tzinfo=UTC)
    assert result.observations[0].valid_until == datetime(2026, 9, 26, 11, tzinfo=UTC)
    assert all(timeout <= 10 for _, timeout in transport.urls)


def test_blank_city_is_rejected_without_network_access():
    transport = FakeTransport([])
    with pytest.raises(ValueError, match="city"):
        WeatherService(OpenMeteoWeatherProvider(transport=transport)).query("  ")
    assert transport.urls == []


def test_ambiguous_city_is_returned_as_choices_not_first_match():
    transport = FakeTransport([{"results": [
        {"id": 1, "name": "Springfield", "latitude": 1, "longitude": 2, "country": "A", "timezone": "UTC"},
        {"id": 2, "name": "Springfield", "latitude": 3, "longitude": 4, "country": "B", "timezone": "UTC"},
    ]}])
    with pytest.raises(WeatherLocationAmbiguous) as error:
        OpenMeteoWeatherProvider(transport=transport).current("Springfield")
    assert [choice.country for choice in error.value.choices] == ["A", "B"]
    assert len(transport.urls) == 1


def test_explicit_choice_is_verified_against_city_candidates_before_fetching():
    transport = FakeTransport([
        {"results": [
            {"id": 1, "name": "Springfield", "latitude": 1, "longitude": 2, "country": "A", "timezone": "UTC"},
            {"id": 2, "name": "Springfield", "latitude": 3, "longitude": 4, "country": "B", "timezone": "UTC"},
        ]},
        {"timezone": "UTC", "current": {"time": "2026-09-26T12:00", "weather_code": 0}},
    ])
    selected = WeatherLocationChoice("Springfield", 3, 4, "UTC", "B")

    result = OpenMeteoWeatherProvider(transport=transport).current_selected("Springfield", selected)

    params = parse_qs(urlparse(transport.urls[1][0]).query)
    assert result.location.latitude == 3
    assert result.location.country == "B"
    assert float(params["latitude"][0]) == 3


def test_unverified_explicit_location_choice_is_rejected():
    transport = FakeTransport([geocoded()])
    selected = WeatherLocationChoice("Paris", 80, 2, "Europe/Paris", "France")

    with pytest.raises(Exception, match="does not match"):
        OpenMeteoWeatherProvider(transport=transport).current_selected("Paris", selected)
    assert len(transport.urls) == 1


@pytest.mark.parametrize(("code", "condition"), [(0, "clear"), (2, "partly_cloudy"), (3, "overcast"),
    (45, "fog"), (61, "rain"), (71, "snow"), (95, "rain"), (777, None)])
def test_weather_code_mapping(code, condition):
    transport = FakeTransport([geocoded(), {"timezone": "Europe/Paris", "current": {
        "time": "2026-09-26T12:00", "weather_code": code}}])
    result = OpenMeteoWeatherProvider(transport=transport).current("Paris")
    assert result.observations[0].condition == condition


def test_weather_provider_uses_open_meteo_geocoding_and_forecast_endpoints():
    transport = FakeTransport([geocoded(), {"timezone": "Europe/Paris", "current": {
        "time": "2026-09-26T12:00", "weather_code": 0}}])
    OpenMeteoWeatherProvider(transport=transport).current("Paris")
    assert urlparse(transport.urls[0][0]).hostname == "geocoding-api.open-meteo.com"
    assert urlparse(transport.urls[1][0]).hostname == "api.open-meteo.com"
    assert parse_qs(urlparse(transport.urls[0][0]).query)["name"] == ["Paris"]


def test_forecast_is_normalized_and_clipped_to_the_user_requested_window():
    transport = FakeTransport([geocoded(), {"timezone": "Europe/Paris", "hourly": {
        "time": ["2026-09-26T12:00", "2026-09-26T13:00", "2026-09-26T14:00"],
        "weather_code": [0, 61, 71], "cloud_cover": [2, 90, 100],
        "precipitation": [0, 1.2, 0], "visibility": [24000, 10000, 500],
    }}])
    start = datetime(2026, 9, 26, 10, tzinfo=UTC)
    end = datetime(2026, 9, 26, 12, tzinfo=UTC)
    provider = OpenMeteoWeatherProvider(transport=transport)

    result = provider.forecast("Paris", start, end)

    assert [row.condition for row in result.observations] == ["clear", "rain"]
    assert result.observations[1].observed_at == datetime(2026, 9, 26, 11, tzinfo=UTC)
    assert result.observations[1].valid_until == datetime(2026, 9, 26, 12, tzinfo=UTC)
    hourly_params = parse_qs(urlparse(transport.urls[1][0]).query)
    assert hourly_params["forecast_days"] == ["7"]


def test_service_rejects_invalid_or_out_of_horizon_forecast_without_network():
    transport = FakeTransport([])
    service = WeatherService(OpenMeteoWeatherProvider(transport=transport),
        clock=lambda: datetime(2026, 9, 26, 10, tzinfo=UTC))
    with pytest.raises(ValueError, match="timezone-aware"):
        service.query("Paris", datetime(2026, 9, 26), datetime(2026, 9, 26, 11, tzinfo=UTC))
    with pytest.raises(ValueError, match="seven days"):
        service.query("Paris", datetime(2026, 9, 26, 10, tzinfo=UTC),
                      datetime(2026, 10, 4, 10, tzinfo=UTC))
    assert not transport.urls


@pytest.mark.parametrize("bad_payload", [None, {}, {"results": [{"name": "Paris", "latitude": 999,
    "longitude": 0, "timezone": "UTC"}]}])
def test_invalid_geocoding_payload_is_a_provider_failure(bad_payload):
    with pytest.raises(Exception):
        OpenMeteoWeatherProvider(transport=FakeTransport([bad_payload])).current("Paris")


def test_provider_transport_errors_become_unavailable_and_never_fake_clear():
    result = WeatherService(OpenMeteoWeatherProvider(transport=FakeTransport([TimeoutError("slow")]))).query("Paris")
    assert result.availability == "unavailable"
    assert result.observations == ()
    assert result.source == "Open-Meteo"


def test_unavailable_forecast_does_not_hide_provider_failure():
    provider = OpenMeteoWeatherProvider(transport=FakeTransport([geocoded(), OSError("offline")]))
    result = WeatherService(provider).query("Paris")
    assert result.availability == "unavailable"
    assert result.observations == ()


def test_no_result_is_unavailable_and_has_no_stored_location_side_effect():
    provider = OpenMeteoWeatherProvider(transport=FakeTransport([{"results": []}, {"results": []}]))
    service = WeatherService(provider)
    assert service.query("Nowhere").availability == "unavailable"
    assert service.query("Nowhere").availability == "unavailable"

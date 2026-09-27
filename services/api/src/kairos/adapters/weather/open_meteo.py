"""Open-Meteo geocoding and current-weather adapter for non-commercial prototypes."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from kairos.application.weather import (
    WeatherLocation,
    WeatherLocationAmbiguous,
    WeatherLocationChoice,
    WeatherObservation,
    WeatherResult,
)


class JsonTransport(Protocol):
    def get_json(self, url: str, *, timeout: float) -> Any: ...


class UrllibJsonTransport:
    def get_json(self, url: str, *, timeout: float) -> Any:
        with urlopen(url, timeout=timeout) as response:
            if response.status != 200:
                raise OSError(f"weather provider returned HTTP {response.status}")
            return json.loads(response.read().decode("utf-8"))


class WeatherProviderError(RuntimeError):
    """Supplier response failed validation or could not be fetched."""


class WeatherLocationNotFound(WeatherProviderError):
    pass


class OpenMeteoWeatherProvider:
    source = "Open-Meteo"
    attribution = "Weather data by Open-Meteo (CC BY 4.0)"
    geocoding_url = "https://geocoding-api.open-meteo.com/v1/search"
    forecast_url = "https://api.open-meteo.com/v1/forecast"
    timeout_seconds = 8.0

    def __init__(self, transport: JsonTransport | None = None) -> None:
        self._transport = transport or UrllibJsonTransport()

    def current(self, city: str) -> WeatherResult:
        if not isinstance(city, str) or not city.strip():
            raise ValueError("An explicit city is required for a weather query")
        try:
            location = self._resolve(city.strip())
            payload = self._transport.get_json(self._forecast_url(location), timeout=self.timeout_seconds)
            observation = self._parse_current(payload, location)
        except WeatherLocationAmbiguous:
            raise
        except WeatherProviderError:
            raise
        except (OSError, URLError, TimeoutError, ValueError, TypeError, KeyError) as exc:
            raise WeatherProviderError("Open-Meteo weather request failed") from exc
        return WeatherResult(
            availability="available", location=location, source=self.source,
            fetched_at=datetime.now(UTC), observations=(observation,), attribution=self.attribution,
        )

    def current_selected(self, city: str, selection: WeatherLocationChoice) -> WeatherResult:
        location = self._resolve_selection(city, selection)
        try:
            payload = self._transport.get_json(self._forecast_url(location), timeout=self.timeout_seconds)
            observation = self._parse_current(payload, location)
        except WeatherProviderError:
            raise
        except (OSError, URLError, TimeoutError, ValueError, TypeError, KeyError) as exc:
            raise WeatherProviderError("Open-Meteo weather request failed") from exc
        return WeatherResult("available", location, self.source, datetime.now(UTC), (observation,), self.attribution)

    def forecast(self, city: str, from_at: datetime, to_at: datetime) -> WeatherResult:
        if from_at.tzinfo is None or to_at.tzinfo is None or from_at >= to_at:
            raise ValueError("Forecast range must be ordered timezone-aware instants")
        try:
            location = self._resolve(city.strip())
            payload = self._transport.get_json(self._forecast_url(location, forecast=True), timeout=self.timeout_seconds)
            observations = self._parse_hourly(payload, location, from_at, to_at)
        except WeatherLocationAmbiguous:
            raise
        except WeatherProviderError:
            raise
        except (OSError, URLError, TimeoutError, ValueError, TypeError, KeyError) as exc:
            raise WeatherProviderError("Open-Meteo forecast request failed") from exc
        return WeatherResult(
            availability="available", location=location, source=self.source,
            fetched_at=datetime.now(UTC), observations=observations, attribution=self.attribution,
        )

    def forecast_selected(self, city: str, selection: WeatherLocationChoice,
                          from_at: datetime, to_at: datetime) -> WeatherResult:
        if from_at.tzinfo is None or to_at.tzinfo is None or from_at >= to_at:
            raise ValueError("Forecast range must be ordered timezone-aware instants")
        location = self._resolve_selection(city, selection)
        try:
            payload = self._transport.get_json(self._forecast_url(location, forecast=True), timeout=self.timeout_seconds)
            observations = self._parse_hourly(payload, location, from_at, to_at)
        except WeatherProviderError:
            raise
        except (OSError, URLError, TimeoutError, ValueError, TypeError, KeyError) as exc:
            raise WeatherProviderError("Open-Meteo forecast request failed") from exc
        return WeatherResult("available", location, self.source, datetime.now(UTC), observations, self.attribution)

    def _resolve(self, city: str) -> WeatherLocation:
        choices = self._search(city)
        if not choices:
            return _raise_not_found()
        if len(choices) > 1:
            raise WeatherLocationAmbiguous(city, choices)
        choice = choices[0]
        return WeatherLocation(choice.name, choice.latitude, choice.longitude, choice.timezone,
                               choice.country, choice.admin1)

    def _search(self, city: str) -> tuple[WeatherLocationChoice, ...]:
        url = f"{self.geocoding_url}?{urlencode({'name': city, 'count': 5, 'language': 'en', 'format': 'json'})}"
        payload = self._transport.get_json(url, timeout=self.timeout_seconds)
        if not isinstance(payload, dict):
            raise WeatherProviderError("Invalid geocoding response")
        results = payload.get("results")
        if results is None:
            return _raise_not_found()
        if not isinstance(results, list):
            raise WeatherProviderError("Invalid geocoding response")
        choices = tuple(_parse_choice(item) for item in results)
        return choices

    def _resolve_selection(self, city: str, selection: WeatherLocationChoice) -> WeatherLocation:
        if not city.strip():
            raise ValueError("An explicit city is required")
        choices = self._search(city.strip())
        if not choices:
            raise WeatherLocationNotFound(f"No location matches {city!r}")
        match = next((choice for choice in choices if _same_choice(choice, selection)), None)
        if match is None:
            raise WeatherProviderError("Selected location does not match a current city candidate")
        return WeatherLocation(match.name, match.latitude, match.longitude, match.timezone,
                               match.country, match.admin1)

    def _forecast_url(self, location: WeatherLocation, *, forecast: bool = False) -> str:
        params = {
            "latitude": location.latitude,
            "longitude": location.longitude,
            "timezone": location.timezone,
        }
        if forecast:
            params.update({"hourly": "weather_code,cloud_cover,precipitation,visibility", "forecast_days": 7})
        else:
            params["current"] = "temperature_2m,weather_code,cloud_cover,precipitation,visibility"
        return f"{self.forecast_url}?{urlencode(params)}"

    def _parse_hourly(self, payload: Any, location: WeatherLocation,
                      from_at: datetime, to_at: datetime) -> tuple[WeatherObservation, ...]:
        if not isinstance(payload, dict) or not isinstance(payload.get("hourly"), dict):
            raise WeatherProviderError("Hourly forecast is missing")
        hourly = payload["hourly"]
        times = hourly.get("time")
        codes = hourly.get("weather_code")
        clouds = hourly.get("cloud_cover")
        precipitation = hourly.get("precipitation")
        visibility = hourly.get("visibility")
        if not isinstance(times, list) or not isinstance(codes, list):
            raise WeatherProviderError("Invalid hourly forecast")
        if not (len(times) == len(codes) == len(clouds or []) == len(precipitation or []) == len(visibility or [])):
            raise WeatherProviderError("Hourly forecast arrays have inconsistent lengths")
        rows: list[WeatherObservation] = []
        for index, raw_time in enumerate(times):
            observed_at = _parse_provider_time(raw_time, location.timezone)
            if observed_at is None:
                raise WeatherProviderError("Invalid hourly forecast time")
            if not from_at.astimezone(UTC) <= observed_at < to_at.astimezone(UTC):
                continue
            code = codes[index]
            if code is not None and (not isinstance(code, int) or isinstance(code, bool)):
                raise WeatherProviderError("Invalid hourly weather code")
            rows.append(WeatherObservation(
                _condition(code),
                _bounded_percent(clouds[index]) if clouds else None,
                _bounded_nonnegative(precipitation[index]) if precipitation else None,
                _bounded_nonnegative(visibility[index]) if visibility else None,
                observed_at,
                observed_at + timedelta(hours=1),
            ))
        return tuple(rows)

    def _parse_current(self, payload: Any, location: WeatherLocation) -> WeatherObservation:
        if not isinstance(payload, dict):
            raise WeatherProviderError("Invalid current weather response")
        current = payload.get("current")
        if not isinstance(current, dict):
            raise WeatherProviderError("Current weather is missing")
        observed_at = _parse_provider_time(current.get("time"), location.timezone)
        valid_until = observed_at + timedelta(hours=1) if observed_at else None
        code = current.get("weather_code")
        if code is not None and (not isinstance(code, int) or isinstance(code, bool)):
            raise WeatherProviderError("Invalid weather code")
        return WeatherObservation(
            condition=_condition(code),
            cloud_cover=_bounded_percent(current.get("cloud_cover")),
            precipitation=_bounded_nonnegative(current.get("precipitation")),
            visibility=_bounded_nonnegative(current.get("visibility")),
            observed_at=observed_at,
            valid_until=valid_until,
        )


def _raise_not_found() -> None:
    raise WeatherLocationNotFound("Location was not found")


def _parse_choice(value: Any) -> WeatherLocationChoice:
    if not isinstance(value, dict):
        raise WeatherProviderError("Invalid geocoding result")
    try:
        name = value["name"]
        latitude = float(value["latitude"])
        longitude = float(value["longitude"])
        timezone = value["timezone"]
    except (KeyError, TypeError, ValueError) as exc:
        raise WeatherProviderError("Invalid geocoding result") from exc
    if not isinstance(name, str) or not name.strip() or not isinstance(timezone, str):
        raise WeatherProviderError("Invalid geocoding result")
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise WeatherProviderError("Coordinates are outside valid ranges")
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise WeatherProviderError("Invalid timezone in geocoding result") from exc
    country = value.get("country") if isinstance(value.get("country"), str) else None
    admin1 = value.get("admin1") if isinstance(value.get("admin1"), str) else None
    return WeatherLocationChoice(name.strip(), latitude, longitude, timezone, country, admin1)


def _same_choice(left: WeatherLocationChoice, right: WeatherLocationChoice) -> bool:
    return (left.name == right.name and left.latitude == right.latitude and left.longitude == right.longitude and
            left.timezone == right.timezone and left.country == right.country and left.admin1 == right.admin1)


def _parse_provider_time(value: Any, timezone: str) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo(timezone))
        return parsed.astimezone(UTC)
    except (ValueError, ZoneInfoNotFoundError):
        return None


def _bounded_percent(value: Any) -> float | None:
    number = _bounded_nonnegative(value)
    if number is None:
        return None
    if number > 100:
        raise WeatherProviderError("Percentage is outside valid range")
    return number


def _bounded_nonnegative(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise WeatherProviderError("Invalid numeric weather value")
    try:
        number = float(value)
    except (ValueError, TypeError) as exc:
        raise WeatherProviderError("Invalid numeric weather value") from exc
    if number < 0 or number != number or number == float("inf"):
        raise WeatherProviderError("Invalid numeric weather value")
    return number


def _condition(code: int | None) -> str | None:
    if code is None:
        return None
    if code == 0:
        return "clear"
    if code in (1, 2):
        return "partly_cloudy"
    if code == 3:
        return "overcast"
    if code in (45, 48):
        return "fog"
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99):
        return "rain"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    return None

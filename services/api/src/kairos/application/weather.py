"""Read-only weather query use case; it deliberately owns no location storage."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Callable, Protocol


@dataclass(frozen=True)
class WeatherLocation:
    name: str
    latitude: float
    longitude: float
    timezone: str
    country: str | None = None
    admin1: str | None = None


@dataclass(frozen=True)
class WeatherObservation:
    condition: str | None
    cloud_cover: float | None
    precipitation: float | None
    visibility: float | None
    observed_at: datetime | None
    valid_until: datetime | None


@dataclass(frozen=True)
class WeatherResult:
    availability: str
    location: WeatherLocation | None
    source: str | None
    fetched_at: datetime | None
    observations: tuple[WeatherObservation, ...]
    attribution: str | None = None
    detail: str | None = None


class WeatherProvider(Protocol):
    source: str
    attribution: str

    def current(self, city: str) -> WeatherResult: ...

    def forecast(self, city: str, from_at: datetime, to_at: datetime) -> WeatherResult: ...

    def current_selected(self, city: str, selection: "WeatherLocationChoice") -> WeatherResult: ...

    def forecast_selected(self, city: str, selection: "WeatherLocationChoice", from_at: datetime,
                          to_at: datetime) -> WeatherResult: ...


@dataclass(frozen=True)
class WeatherLocationChoice:
    name: str
    latitude: float
    longitude: float
    timezone: str
    country: str | None = None
    admin1: str | None = None


class WeatherLocationAmbiguous(ValueError):
    """The user must select one of several matching locations."""

    def __init__(self, city: str, choices: tuple[WeatherLocationChoice, ...]) -> None:
        self.city = city
        self.choices = choices
        super().__init__(f"More than one place matches {city!r}; ask the user to choose.")


class WeatherService:
    """Execute weather reads only when called by an explicit user query."""

    def __init__(self, provider: WeatherProvider, clock: Callable[[], datetime] | None = None) -> None:
        self._provider = provider
        self._clock = clock or (lambda: datetime.now().astimezone())

    def query(self, city: str, from_at: datetime | None = None,
              to_at: datetime | None = None,
              selection: "WeatherLocationChoice | None" = None) -> WeatherResult:
        if not isinstance(city, str) or not city.strip():
            raise ValueError("An explicit city is required for a weather query")
        if (from_at is None) != (to_at is None):
            raise ValueError("Both forecast range endpoints are required")
        if from_at is not None and to_at is not None:
            if from_at.tzinfo is None or to_at.tzinfo is None or from_at >= to_at:
                raise ValueError("Forecast range must be ordered timezone-aware instants")
            if (to_at - from_at).total_seconds() > 7 * 24 * 60 * 60:
                raise ValueError("Forecast range cannot exceed seven days")
            now = self._clock().astimezone(UTC)
            if from_at.astimezone(UTC) < now - timedelta(hours=1):
                raise ValueError("Open-Meteo forecast queries must be current or future")
            if to_at.astimezone(UTC) > now + timedelta(days=7):
                raise ValueError("Forecast end is beyond the available seven-day horizon")
        try:
            if from_at is None or to_at is None:
                if selection is None:
                    result = self._provider.current(city.strip())
                else:
                    result = self._provider.current_selected(city.strip(), selection)
            else:
                if selection is None:
                    result = self._provider.forecast(city.strip(), from_at, to_at)
                else:
                    result = self._provider.forecast_selected(city.strip(), selection, from_at, to_at)
        except WeatherLocationAmbiguous:
            raise
        except Exception:
            # External data is best-effort. Never turn a provider failure into a
            # fabricated clear-sky result or retain the requested city.
            return WeatherResult("unavailable", None, self._provider.source,
                                 self._clock().astimezone(UTC), (), self._provider.attribution,
                                 "Weather service is temporarily unavailable.")
        fetched_at = self._clock().astimezone(UTC)
        stale = bool(result.observations) and all(
            observation.valid_until is not None and observation.valid_until < fetched_at
            for observation in result.observations
        )
        return replace(result, availability="stale" if stale else result.availability,
                       fetched_at=fetched_at)

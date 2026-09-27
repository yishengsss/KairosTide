"""Exercise the health and state HTTP contracts in an isolated database."""

import json
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/api/src"))

from kairos.api.schemas import StateResponse, WeatherResponse  # noqa: E402
from kairos.application.weather import WeatherResult  # noqa: E402
from kairos.main import create_app  # noqa: E402


class UnavailableWeatherProvider:
    source = "Open-Meteo"
    attribution = "Weather data by Open-Meteo (CC BY 4.0)"

    def current(self, _city):
        return WeatherResult("unavailable", None, self.source, None, (), self.attribution,
                             "Weather service is temporarily unavailable.")

    def forecast(self, _city, _from_at, _to_at):
        return self.current(_city)


def main(openapi_file: Path) -> int:
    with tempfile.TemporaryDirectory(prefix="kairos-contract-http-") as directory:
        app = create_app(str(Path(directory) / "runtime.sqlite3"), weather_provider=UnavailableWeatherProvider())
        with TestClient(app) as client:
            runtime_spec = client.get("/openapi.json")
            if runtime_spec.status_code != 200 or runtime_spec.json() != json.loads(openapi_file.read_text()):
                print("FAIL K15-HTTP: served OpenAPI differs from generated artifact")
                return 1
            health = client.get("/api/v1/health")
            if health.status_code != 200 or health.json() != {"status": "ok"}:
                print("FAIL K01-HTTP: new runtime health failed")
                return 1
            state = client.get("/api/v1/state")
            if state.status_code != 200:
                print("FAIL K15-HTTP: state query failed")
                return 1
            StateResponse.model_validate(state.json())
            weather = client.get("/api/v1/weather", params={"location_id": "home"})
            if weather.status_code != 200:
                print("FAIL K15-HTTP: weather read contract failed")
                return 1
            parsed_weather = WeatherResponse.model_validate(weather.json())
            if parsed_weather.availability != "unavailable" or parsed_weather.observations:
                print("FAIL K15-HTTP: weather fallback fabricated facts")
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))

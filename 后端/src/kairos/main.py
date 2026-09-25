from fastapi import FastAPI

from kairos.adapters.clock import SystemClock
from kairos.adapters.openai_compatible import OpenAICompatiblePlanner
from kairos.adapters.sqlite import SQLiteStore
from kairos.api.routes import router
from kairos.application.drafts import DraftCommands
from kairos.application.events import EventCommands
from kairos.application.state import Clock, EventQueries
from kairos.settings import Settings


def create_app(settings: Settings | None = None, clock: Clock | None = None) -> FastAPI:
    """Assemble the HTTP app without touching persistence or calling a model."""
    runtime_settings = settings or Settings()
    app = FastAPI(title="Kairos Backend", version="0.1.0")
    app.state.settings = runtime_settings
    runtime_clock = clock or SystemClock()
    store = SQLiteStore(runtime_settings.db_path)
    app.state.event_queries = EventQueries(store, runtime_clock)
    app.state.event_commands = EventCommands(store, runtime_clock)
    if (
        runtime_settings.ai_provider == "openai_compatible"
        and runtime_settings.ai_api_key
        and runtime_settings.ai_base_url
        and runtime_settings.ai_model
    ):
        app.state.planner = OpenAICompatiblePlanner(
            runtime_settings.ai_base_url,
            runtime_settings.ai_api_key,
            runtime_settings.ai_model,
        )
    else:
        app.state.planner = None
    app.state.draft_commands = (
        DraftCommands(store, app.state.planner, runtime_clock)
        if app.state.planner is not None
        else None
    )

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(router)
    return app


app = create_app()

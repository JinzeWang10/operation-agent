from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "operation-agent"
    debug: bool = False

    # Timeouts (seconds)
    timeout_total: int = 120
    timeout_adapter: int = 15
    timeout_phase2: int = 60
    phase2_max_rounds: int = 3

    # LLM
    llm_api_key: str = ""
    llm_base_url: str = "http://localhost:8000/v1"
    llm_model: str = "gpt-4o"
    llm_temperature: float = 0.1

    # Time window
    default_time_window_minutes: int = 60

    model_config = {"env_file": ".env", "env_prefix": "AGENT_"}

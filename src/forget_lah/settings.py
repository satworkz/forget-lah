from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")
    app_env: Literal["local", "test"] = "local"
    database_url: SecretStr
    public_origin: str = "http://localhost:8080"
    mock_clinic_url: str = "http://mock-clinic:8001"
    mock_clinic_admin_key: SecretStr | None = None
    mock_clinic_followup_key: SecretStr | None = None
    patient_simulator_enabled: bool = False
    demo_reset_enabled: bool = False
    agent_auto_start_enabled: bool = True
    session_hours: int = 4
    demo_staff_email: str = "staff@forget-lah.example"
    demo_staff_password: SecretStr | None = None
    agent_model_mode: Literal["mock", "organiser", "anthropic"] = "mock"
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-sonnet-4-5-20250929"
    anthropic_workspace_id: str = ""
    llm_gateway_url: str = ""
    llm_gateway_api_key: SecretStr | None = None
    llm_model: str = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
    agent_max_steps: int = Field(default=24, ge=4, le=40)
    agent_daily_call_limit: int = Field(default=40, ge=1, le=400)
    agent_request_max_bytes: int = Field(default=8000, ge=2000, le=64000)
    agent_min_interval_seconds: int = Field(default=2, ge=0, le=30)

    @property
    def simulation_configured(self) -> bool:
        return bool(
            self.patient_simulator_enabled
            and self.mock_clinic_followup_key
            and self.mock_clinic_followup_key.get_secret_value().strip()
        )

    @property
    def model_configured(self) -> bool:
        if self.agent_model_mode == "mock":
            return True
        key = (
            self.anthropic_api_key
            if self.agent_model_mode == "anthropic"
            else self.llm_gateway_api_key
        )
        return bool(
            key
            and key.get_secret_value().strip()
            and (self.agent_model_mode == "anthropic" or self.llm_gateway_url.strip())
        )

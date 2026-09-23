import os
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")
    app_env: Literal["local", "test", "demo"] = "local"
    database_url: SecretStr
    public_origin: str = "http://localhost:8080"
    mock_clinic_url: str = "http://mock-clinic:8001"
    mock_clinic_admin_key: SecretStr | None = None
    mock_clinic_followup_key: SecretStr | None = None
    patient_simulator_enabled: bool = False
    demo_reset_enabled: bool = False
    whatsapp_enabled: bool = False
    multilingual_enabled: bool = False

    @property
    def translation_configured(self) -> bool:
        return (
            self.multilingual_enabled
            and self.agent_model_mode == "anthropic"
            and self.model_configured
        )

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
    agent_max_steps: int = Field(default=40, ge=4, le=40)
    agent_daily_call_limit: int = Field(default=40, ge=1, le=400)
    agent_request_max_bytes: int = Field(default=32000, ge=2000, le=64000)
    agent_step_delay_seconds: float = Field(default=0, ge=0, le=30)
    agent_parallelism: int = Field(default=2, ge=1, le=4)
    worker_idle_seconds: float = Field(default=0.25, ge=0.05, le=5)
    source_poll_interval_seconds: float = Field(default=2, ge=1, le=60)
    agent_required_reads_enabled: bool = True
    agent_min_interval_seconds: int = Field(default=2, ge=0, le=30)

    # Optional closed-set decider (Lane A, System One shape). The flag is the rollout
    # switch: off restores ordinary provider selection with no migration and no data loss.
    agent_decider_enabled: bool = False
    # Hosted baseline is the Decision model typesafe/jev on the Provider API.
    agent_decider_url: str = "https://api.commandcode.ai/provider"
    # Standby, selected only when AGENT_DECIDER_URL is explicitly empty. A failed selected
    # endpoint never retries another endpoint; the whole decision falls back to the inner
    # provider. Local Kev-4B speaks the same route for offline work.
    agent_decider_fallback_url: str = "http://172.17.0.1:8009"
    agent_decider_model: str = "typesafe/jev"
    agent_decider_timeout: float = Field(default=30, gt=0, le=30)
    # Gate policy is explicit, versioned and sweepable: the A/B harness varies the mode and the
    # thresholds and replays recorded answers instead of spending live calls (astra GATE: D).
    # The defaults preserve pre-decision behaviour until measurement chooses thresholds.
    agent_decider_gate_mode: Literal["confidence", "probability", "joint"] = "confidence"
    agent_decider_min_confidence: float = Field(default=0.5, ge=0, le=1)
    agent_decider_min_probability: float = Field(default=0.0, ge=0, le=1)
    agent_decider_min_margin: float = Field(default=0.0, ge=0, le=1)
    agent_decider_shadow: bool = False
    agent_decider_record: str = ""

    @property
    def agent_decider_api_key(self) -> SecretStr | None:
        """Environment-only secret: not a settings field, so it cannot be dumped."""
        value = os.environ.get("AGENT_DECIDER_API_KEY", "")
        return SecretStr(value) if value.strip() else None

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

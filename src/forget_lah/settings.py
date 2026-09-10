from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")
    app_env: Literal["local", "test"] = "local"
    database_url: SecretStr
    public_origin: str = "http://localhost:8080"
    mock_clinic_url: str = "http://mock-clinic:8001"
    session_hours: int = 4
    demo_staff_email: str = "staff@forget-lah.example"
    demo_staff_password: SecretStr | None = None

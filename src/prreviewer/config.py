from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    github_app_id: str = ""
    github_app_private_key_path: str = "./github-app-private-key.pem"
    github_webhook_secret: str = ""

    llm_api_key: str = ""
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "z-ai/glm-5.2:free"

    redis_url: str = "redis://localhost:6379/0"

    max_files_per_pr: int = 40
    max_file_bytes: int = 200_000
    skip_bot_authors: bool = True

    @property
    def github_app_private_key(self) -> str:
        return Path(self.github_app_private_key_path).read_text()


@lru_cache
def get_settings() -> Settings:
    return Settings()

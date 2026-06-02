from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        env_ignore_empty=True,
    )

    TELEGRAM_TOKEN: str = ""
    ANTHROPIC_API_KEY: str = ""
    DATABASE_URL: str = "sqlite:///./second_brain.db"
    DATA_PATH: Path = Path("./data")

    CLAUDE_INPUT_PRICE_PER_1M: float = 3.0
    CLAUDE_OUTPUT_PRICE_PER_1M: float = 15.0

    DEFAULT_MODEL: str = "claude-sonnet-4-6"


settings = Settings()

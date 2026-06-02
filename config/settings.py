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
    DATABASE_URL: str = "sqlite:///./data/second_brain.db"
    DATA_PATH: Path = Path("./data")

    # Comma-separated Telegram user IDs with unlimited access (owners/devs)
    OWNER_USER_IDS: str = ""

    @property
    def owner_ids(self) -> set[str]:
        return {uid.strip() for uid in self.OWNER_USER_IDS.split(",") if uid.strip()}

    CLAUDE_INPUT_PRICE_PER_1M: float = 3.0
    CLAUDE_OUTPUT_PRICE_PER_1M: float = 15.0
    HAIKU_INPUT_PRICE_PER_1M: float = 0.8
    HAIKU_OUTPUT_PRICE_PER_1M: float = 4.0

    DEFAULT_MODEL: str = "claude-sonnet-4-6"
    FAST_MODEL: str = "claude-haiku-4-5-20251001"

    # Max chars of raw text sent to classifier (covers ~3K tokens)
    CLASSIFIER_INPUT_LIMIT: int = 12000

    # Todoist integration (optional)
    TODOIST_API_KEY: str = ""


settings = Settings()

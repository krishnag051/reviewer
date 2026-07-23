from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg2://tpuser:tppass@localhost:5432/tpreview"
    jwt_secret: str = "change-me-in-real-deploys"
    jwt_expires_minutes: int = 720
    retention_days_default: int = 30
    upload_storage_dir: str = "./data/uploads"


settings = Settings()

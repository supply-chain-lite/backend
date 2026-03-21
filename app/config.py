from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    secret_key: str = "change-me"
    access_token_expire_minutes: int = 30
    sqlite_db_path: str = "./data.db"


settings = Settings()

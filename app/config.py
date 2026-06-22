from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_path: str = "tasks.db"

settings = Settings()
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://portfaio:portfaio@localhost:5432/portfaio"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:14b"
    finnhub_api_key: str = ""
    news_api_key: str = ""

    class Config:
        env_file = ".env"


settings = Settings()

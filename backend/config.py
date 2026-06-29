from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://portfaio:portfaio@localhost:5432/portfaio"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:14b"
    finnhub_api_key: str = ""
    news_api_key: str = ""
    # Obergrenze (Sekunden) für blockierende yfinance-Calls; verhindert, dass ein
    # hängender Download/Info-Abruf den Request unbegrenzt blockiert.
    yfinance_timeout: float = 30.0

    # Erlaubte CORS-Origins (Komma-getrennt). Default = lokale Dev-Ports; fürs Hosting
    # die Produktions-Origin per Env setzen (CORS_ORIGINS=...).
    cors_origins: str = (
        "http://localhost:5173,http://localhost:5174,http://localhost:5175,"
        "http://localhost:3000,http://localhost:8080"
    )

    # DB-Connection-Pool (greift nur bei Server-DBs wie Postgres; bei SQLite ignoriert).
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_recycle: int = 1800       # Sekunden — abgestandene Verbindungen recyceln
    db_pool_pre_ping: bool = True     # tote Verbindungen vor Nutzung erkennen

    class Config:
        env_file = ".env"


settings = Settings()

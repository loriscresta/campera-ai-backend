from __future__ import annotations
from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    anthropic_api_key: str = ""
    mapbox_token: str = ""
    openweather_api_key: str = ""
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    # Alternative Overpass endpoints (load balancing)
    overpass_mirrors: list[str] = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    ]
    claude_model: str = "claude-sonnet-4-5"
    max_tokens: int = 8192
    cors_origins: list[str] = ["*"]  # stringe in produzione
    
    class Config:
        env_file = ".env"

@lru_cache
def get_settings() -> Settings:
    return Settings()

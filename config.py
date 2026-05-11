from __future__ import annotations
import os
from functools import lru_cache
from dotenv import load_dotenv

load_dotenv()

class Settings:
    def __init__(self):
        self.anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
        self.mapbox_token: str = os.getenv("MAPBOX_TOKEN", "")
        self.overpass_url: str = os.getenv("OVERPASS_URL", "https://overpass-api.de/api/interpreter")
        self.claude_model: str = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5")
        self.fast_model: str = os.getenv("FAST_MODEL", "claude-haiku-4-5-20251001")
        self.max_tokens: int = int(os.getenv("MAX_TOKENS", "8192"))
        self.cors_origins: list = ["*"]

@lru_cache
def get_settings() -> Settings:
    return Settings()


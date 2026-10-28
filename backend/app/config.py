from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://quantbook:quantbook_dev@127.0.0.1:5433/quantbook"
    storage_root: Path = Path("./storage")
    max_upload_mb: int = 100
    ai_provider: str = "offline"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_vision_model: str = "gemma3:4b"
    ollama_text_model: str = "qwen3:4b"
    ollama_embed_model: str = "nomic-embed-text"
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
settings = Settings()

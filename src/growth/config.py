from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GROWTH_", env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./growth.db"
    vendor_database_url: str = "sqlite:///./vendor.db"
    execution: str = "inline"
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    kafka_servers: str = "localhost:9092"
    auth_secret: str = ""
    oidc_issuer: str = ""
    oidc_audience: str = "growth-api"
    oidc_jwks_url: str = ""
    policy_path: str = "workflows/agent-policies.yaml"


@lru_cache
def settings() -> Settings:
    return Settings()

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GROWTH_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )
    database_url: str = "sqlite:///./growth.db"
    vendor_database_url: str = "sqlite:///./vendor.db"
    execution: str = "inline"
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    kafka_servers: str = "localhost:9092"
    kafka_security_protocol: Literal["PLAINTEXT", "SSL", "SASL_SSL"] = "PLAINTEXT"
    kafka_sasl_mechanism: Literal["PLAIN", "SCRAM-SHA-512", "OAUTHBEARER"] = "SCRAM-SHA-512"
    kafka_username: str = ""
    kafka_password: SecretStr = SecretStr("")
    kafka_ca_file: str = ""
    temporal_tls: bool = False
    temporal_api_key: SecretStr = SecretStr("")
    temporal_ca_file: str = ""
    temporal_cert_file: str = ""
    temporal_key_file: str = ""
    temporal_server_name: str = ""

    auth_secret: str = ""
    oidc_issuer: str = ""
    oidc_audience: str = "growth-api"
    oidc_jwks_url: str = ""
    otel_enabled: bool = False
    otel_endpoint: str = ""
    region: Literal["us-east-1", "eu-west-1", "ap-southeast-2"] = "us-east-1"
    runtime_mode: Literal["development", "enterprise"] = "development"
    model_provider: Literal["deterministic", "openai_compatible"] = "deterministic"
    model_base_url: str = ""
    model_name: str = ""
    model_region: str = ""
    model_api_key: SecretStr = SecretStr("")
    model_allowed_hosts: list[str] = []
    worker_concurrency: int = 16
    source_bindings: str = (
        '{"console-enterprise-demo":{"tenantId":"tenant-demo","region":"us-east-1"}}'
    )
    sandbox_url: str = ""
    sandbox_allowed_hosts: list[str] = []
    allow_internal_sandbox: bool = False
    sandbox_bindings: SecretStr = SecretStr("{}")
    connector_profiles: SecretStr = SecretStr("{}")
    policy_path: str = "workflows/agent-policies.yaml"

    @model_validator(mode="after")
    def secure_runtime(self) -> "Settings":
        if not 1 <= self.worker_concurrency <= 256:
            raise ValueError("WORKER_CONCURRENCY_INVALID")
        if self.model_provider != "deterministic" and (
            not self.model_api_key.get_secret_value()
            or not self.model_name
            or self.model_region != self.region
        ):
            raise ValueError("MODEL_CONFIGURATION_REQUIRED")
        if self.runtime_mode == "enterprise" and self.allow_internal_sandbox:
            raise ValueError("ENTERPRISE_REQUIRES_HTTPS_SANDBOX")
        if self.runtime_mode == "enterprise" and (
            not self.oidc_issuer.startswith("https://")
            or not self.database_url.startswith("postgresql")
            or self.execution != "temporal"
            or self.kafka_security_protocol == "PLAINTEXT"
            or not self.temporal_tls
            or not (
                self.temporal_api_key.get_secret_value()
                or (self.temporal_cert_file and self.temporal_key_file)
            )
            or "sslmode=verify-full" not in self.database_url
            or "sslmode=verify-full" not in self.vendor_database_url
        ):
            raise ValueError("ENTERPRISE_REQUIRES_OIDC_POSTGRES_TEMPORAL")
        return self


@lru_cache
def settings() -> Settings:
    return Settings()

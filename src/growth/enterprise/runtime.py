from growth.config import Settings
from growth.db import engine
from growth.enterprise.model_gateway import OpenAICompatibleGateway
from growth.enterprise.service import EnterpriseService


def create_service(config: Settings) -> EnterpriseService:
    from growth.observability import initialize

    initialize(config)
    gateway = None
    if config.model_provider == "openai_compatible":
        gateway = OpenAICompatibleGateway(
            config.model_base_url,
            config.model_name,
            config.model_api_key,
            config.model_allowed_hosts,
        )
    service = EnterpriseService(
        engine(config.database_url),
        engine(config.vendor_database_url),
        region=config.region,
        gateway=gateway,
    )

    if config.sandbox_url:
        import json

        from growth.enterprise.execution import SandboxRouter

        service.executor = SandboxRouter(
            json.loads(config.sandbox_bindings.get_secret_value()),
            config.sandbox_url,
            config.sandbox_allowed_hosts,
            config.allow_internal_sandbox,
        )
    if config.connector_profiles.get_secret_value() not in ("{}", ""):
        from growth.connectors.registry import ConnectorRegistry

        registry = ConnectorRegistry(
            config.connector_profiles.get_secret_value(),
            service.vendor_db,
            service.executor,
            service.db,
            config.region,
        )
        service.context_resolver = registry
        service.connector_registry = registry
        service.executor = registry
    return service

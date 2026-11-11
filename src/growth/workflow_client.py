from pathlib import Path

from temporalio.client import Client
from temporalio.service import TLSConfig

from growth.config import Settings


async def connect(config: Settings) -> Client:
    tls: bool | TLSConfig = False
    if config.temporal_tls:
        tls = TLSConfig(
            server_root_ca_cert=Path(config.temporal_ca_file).read_bytes()
            if config.temporal_ca_file
            else None,
            client_cert=Path(config.temporal_cert_file).read_bytes()
            if config.temporal_cert_file
            else None,
            client_private_key=Path(config.temporal_key_file).read_bytes()
            if config.temporal_key_file
            else None,
            domain=config.temporal_server_name or None,
        )
    return await Client.connect(
        config.temporal_address,
        namespace=config.temporal_namespace,
        tls=tls,
        api_key=config.temporal_api_key.get_secret_value() or None,
    )

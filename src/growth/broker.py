from typing import Any

from growth.config import Settings


def configuration(config: Settings) -> dict[str, Any]:
    value: dict[str, Any] = {
        "bootstrap.servers": config.kafka_servers,
        "security.protocol": config.kafka_security_protocol,
    }
    if config.kafka_ca_file:
        value["ssl.ca.location"] = config.kafka_ca_file
    if config.kafka_security_protocol == "SASL_SSL":
        value["sasl.mechanism"] = config.kafka_sasl_mechanism
        if config.kafka_sasl_mechanism == "OAUTHBEARER":
            from aws_msk_iam_sasl_signer import MSKAuthTokenProvider

            def oauth(configuration_string: str) -> tuple[str, float]:
                token, expiry = MSKAuthTokenProvider.generate_auth_token(config.region)
                return str(token), float(expiry) / 1000

            value["oauth_cb"] = oauth
        else:
            value["sasl.username"] = config.kafka_username
            value["sasl.password"] = config.kafka_password.get_secret_value()
    return value

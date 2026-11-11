from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from pydantic import ValidationError

from growth.config import Settings
from growth.contracts import Principal

bearer = HTTPBearer(auto_error=False)


def principal(
    request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
) -> Principal:
    if credentials is None:
        raise HTTPException(401, "AUTHENTICATION_REQUIRED", headers={"WWW-Authenticate": "Bearer"})
    config: Settings = request.app.state.config
    try:
        if config.oidc_issuer:
            jwks: PyJWKClient = request.app.state.jwks
            key = jwks.get_signing_key_from_jwt(credentials.credentials).key
            claims = jwt.decode(
                credentials.credentials,
                key,
                algorithms=["RS256"],
                issuer=config.oidc_issuer,
                audience=config.oidc_audience,
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            )
        else:
            if len(config.auth_secret) < 32:
                raise HTTPException(503, "AUTH_NOT_CONFIGURED")
            claims = jwt.decode(
                credentials.credentials,
                config.auth_secret,
                algorithms=["HS256"],
                audience="growth-api",
                issuer="growth-local",
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            )
        result = Principal(
            subject=claims["sub"],
            identityType=claims.get("identityType", "workload"),
            tenant=claims["tenant"],
            region=claims["region"],
            role=claims["role"],
            purposes=claims["purposes"],
        )
    except (jwt.PyJWTError, ValidationError, KeyError, ValueError):
        raise HTTPException(401, "INVALID_TOKEN") from None
    if "cart_recovery" not in result.purposes:
        raise HTTPException(403, "PURPOSE_DENIED")
    request.state.tenant = result.tenant
    return result


Identity = Annotated[Principal, Depends(principal)]


def require(identity: Principal, *roles: str) -> None:
    if identity.role not in roles:
        raise HTTPException(403, "ROLE_DENIED")

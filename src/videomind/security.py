"""Resolve only the user's explicit environment references. No default credentials."""

import os
from collections.abc import Mapping, Sequence

from pydantic import Field, SecretStr

from videomind.config import Role, Settings, StrictModel
from videomind.errors import ConfigurationError, CredentialsError


class Credential(StrictModel):
    # Omitted from serialization as well as masked in repr; adapters must opt in to access.
    api_key: SecretStr = Field(exclude=True, repr=False)


def resolve_credentials(
    settings: Settings,
    *,
    environ: Mapping[str, str] | None = None,
    roles: Sequence[Role] | None = None,
) -> dict[Role, Credential]:
    """Resolve required roles without reading Codex login, .env or shared key files."""
    environment = os.environ if environ is None else environ
    configured = settings.providers.configured()
    required = list(configured) if roles is None else list(roles)
    if roles is None and not required:
        raise ConfigurationError("没有配置云端 Provider；离线处理无需 Key。")
    credentials: dict[Role, Credential] = {}
    for role in required:
        spec = configured.get(role)
        if spec is None:
            raise ConfigurationError(f"{role}: 尚未配置所需 Provider。")
        value = environment.get(spec.api_key_env, "").strip()
        if not value or value.casefold().startswith(("your_", "placeholder", "change_me")):
            raise CredentialsError(
                f"{role}: 缺少有效的用户 API Key，请在配置指定的环境变量中设置；无共享密钥回退。"
            )
        credentials[role] = Credential(api_key=SecretStr(value))
    return credentials

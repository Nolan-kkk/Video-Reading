import pytest

from videomind.config import load_config
from videomind.errors import ConfigurationError, CredentialsError
from videomind.security import resolve_credentials


@pytest.mark.parametrize("value", [None, "", "   ", "your_api_key_here", "placeholder-key"])
def test_no_fallback_for_missing_or_placeholder_key(config_file, value):
    environment = {"OPENAI_API_KEY": "test-only-unrelated-account"}
    if value is not None:
        environment["VIDEOMIND_TEST_KEY"] = value
    with pytest.raises(CredentialsError):
        resolve_credentials(load_config(config_file), environ=environment)


def test_only_explicit_user_environment_key_is_resolved(config_file):
    secret = "test-only-user-owned-sentinel"
    credentials = resolve_credentials(
        load_config(config_file), environ={"VIDEOMIND_TEST_KEY": secret}
    )
    credential = credentials["vision"]
    assert credential.api_key.get_secret_value() == secret
    assert secret not in repr(credentials)
    assert secret not in str(credential)
    assert credential.model_dump() == {}
    assert credential.model_dump_json() == "{}"


def test_explicit_empty_environment_does_not_use_process_environment(config_file, monkeypatch):
    monkeypatch.setenv("VIDEOMIND_TEST_KEY", "test-only-process-key")
    with pytest.raises(CredentialsError):
        resolve_credentials(load_config(config_file), environ={})


def test_unconfigured_required_capability_fails(config_file):
    with pytest.raises(ConfigurationError):
        resolve_credentials(load_config(config_file), environ={}, roles=["transcription"])

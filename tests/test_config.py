from decimal import Decimal

import pytest
import yaml

from videomind.config import load_config
from videomind.errors import ConfigurationError


def test_defaults_and_relative_output_are_stable(config_file, tmp_path, monkeypatch):
    elsewhere = tmp_path / "caller"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    settings = load_config(config_file)
    assert settings.billing.mode == "user_provided_api_key"
    assert settings.billing.confirm_before_paid_requests is True
    assert settings.billing.max_budget_usd_per_batch == Decimal("5")
    assert settings.output.directory == config_file.parent / "output"
    assert not settings.output.directory.exists()


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("billing", "mode", "maintainer_account"),
        ("billing", "max_budget_usd_per_batch", -1),
        ("billing", "max_budget_usd_per_batch", float("inf")),
        ("billing", "confirm_before_paid_requests", "false"),
        ("video", "max_concurrent_tasks", 0),
        ("video", "max_concurrent_tasks", True),
        ("video", "max_concurrent_tasks", 33),
        ("video", "max_duration_minutes", 0),
        ("video", "max_retries", -1),
        ("vision", "max_frames_per_video", 0),
        ("speech", "enabled", "false"),
        ("speech", "cpu_threads", 0),
        ("speech", "language", "zh;echo unsafe"),
        ("ocr", "enabled", "true"),
        ("ocr", "min_confidence", float("nan")),
        ("ocr", "min_confidence", 1.1),
        ("download", "max_download_mb", 0),
        ("download", "max_height", 0),
        ("download", "timeout_seconds", 0),
        ("output", "mode", "unsupported"),
        ("output", "depth", "unsupported"),
    ],
)
def test_invalid_limits_fail_closed(config_data, config_file, section, field, value):
    config_data[section] = {field: value}
    config_file.write_text(yaml.safe_dump(config_data), encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_config(config_file)


@pytest.mark.parametrize("model", ["", "   ", "YOUR_VISION_MODEL", "placeholder-model"])
def test_model_requires_user_selection(config_data, config_file, model):
    config_data["providers"]["vision"]["model"] = model
    config_file.write_text(yaml.safe_dump(config_data), encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_config(config_file)


@pytest.mark.parametrize(
    "content",
    [
        "providers: [broken",
        "!!python/object/apply:os.system ['echo should-not-execute']",
        "providers: {}\nproviders: {}\n",
        "? [non, scalar, key]\n: value\n",
        "[]",
        "",
    ],
)
def test_unsafe_or_ambiguous_yaml_is_rejected(config_file, content):
    config_file.write_text(content, encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_config(config_file)


@pytest.mark.parametrize("location", ["extra_field", "api_key", "parser_error"])
def test_bad_config_never_echoes_secret(config_file, config_data, location):
    secret = "test-only-sensitive-value-2468"
    if location == "parser_error":
        content = f"providers: [ {secret}"
    else:
        config_data[location] = secret
        content = yaml.safe_dump(config_data)
    config_file.write_text(content, encoding="utf-8")
    with pytest.raises(ConfigurationError) as error:
        load_config(config_file)
    assert secret not in str(error.value)
    assert error.value.__cause__ is None


def test_relative_speech_models_resolve_against_config(config_file):
    settings = load_config(config_file)
    assert (
        settings.speech.model_directory == config_file.parent / ".cache/models/faster-whisper-small"
    )
    assert settings.speech.enabled is False and settings.ocr.enabled is False


def test_missing_config_does_not_echo_filename(tmp_path):
    secret = "test-only-sensitive-filename"
    with pytest.raises(ConfigurationError) as error:
        load_config(tmp_path / secret)
    assert secret not in str(error.value)

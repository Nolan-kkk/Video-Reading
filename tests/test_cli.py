import json
import subprocess
import sys

import pytest

from videomind.cli import main


def test_doctor_is_offline_and_needs_no_key(capsys):
    assert main(["doctor"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["stage"] == "V2-in-progress"
    assert result["paid_requests_enabled"] is False
    assert result["video_analysis_available"] is True
    assert result["batch_analysis_available"] is True


def test_structure_check_does_not_require_credentials(config_file, capsys, monkeypatch):
    monkeypatch.delenv("VIDEOMIND_TEST_KEY", raising=False)
    assert main(["check-config", "--config", str(config_file), "--structure-only"]) == 0
    assert json.loads(capsys.readouterr().out)["credentials"] == "not_checked"


def test_missing_key_has_nonzero_exit_without_traceback(config_file, capsys, monkeypatch):
    monkeypatch.delenv("VIDEOMIND_TEST_KEY", raising=False)
    assert main(["check-config", "--config", str(config_file)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "API Key" in captured.err
    assert "Traceback" not in captured.err


def test_present_key_is_never_printed_or_claimed_verified(config_file, capsys, monkeypatch):
    secret = "test-only-cli-secret"
    monkeypatch.setenv("VIDEOMIND_TEST_KEY", secret)
    assert main(["check-config", "--config", str(config_file)]) == 0
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err
    result = json.loads(captured.out)
    assert result["credentials"] == "present_not_verified"
    assert result["paid_requests_enabled"] is False


def test_unrecognized_key_argument_is_not_echoed(capsys):
    secret = "test-only-accidental-key-argument"
    with pytest.raises(SystemExit) as error:
        main(["doctor", "--api-key", secret])
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err


def test_codex_can_invoke_installed_module_from_another_directory(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "videomind", "doctor"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["paid_requests_enabled"] is False
    assert "本地处理需要" in output["note"]

import os

import pytest

from securebench.env import load_env_file


def test_load_env_file_sets_missing_values(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        """
# comment
OPENAI_API_KEY="test-key"
export LOCAL_LLM_API_KEY=local-key
"""
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LOCAL_LLM_API_KEY", raising=False)

    loaded = load_env_file(env_path)

    assert loaded == {
        "OPENAI_API_KEY": "test-key",
        "LOCAL_LLM_API_KEY": "local-key",
    }
    assert os.environ["OPENAI_API_KEY"] == "test-key"
    assert os.environ["LOCAL_LLM_API_KEY"] == "local-key"


def test_load_env_file_does_not_override_existing_values_by_default(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("OPENAI_API_KEY=file-key\n")
    monkeypatch.setenv("OPENAI_API_KEY", "existing-key")

    loaded = load_env_file(env_path)

    assert loaded == {}
    assert os.environ["OPENAI_API_KEY"] == "existing-key"


def test_load_env_file_can_override_existing_values(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("OPENAI_API_KEY=file-key\n")
    monkeypatch.setenv("OPENAI_API_KEY", "existing-key")

    loaded = load_env_file(env_path, override=True)

    assert loaded == {"OPENAI_API_KEY": "file-key"}
    assert os.environ["OPENAI_API_KEY"] == "file-key"


def test_load_env_file_ignores_missing_file(tmp_path):
    assert load_env_file(tmp_path / "missing.env") == {}


def test_load_env_file_rejects_invalid_lines(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("OPENAI_API_KEY\n")

    with pytest.raises(ValueError, match="expected KEY=VALUE"):
        load_env_file(env_path)

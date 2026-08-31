"""YAML configuration, offline checking, host, and CLI tests."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gateway.cli import main
from gateway.config import (
    ConfigError,
    EnvironmentSecretResolver,
    check_config,
    load_config,
)
from gateway.host import build_host

CONFIG = """
server:
  host: 127.0.0.1
  port: 6186
state:
  type: sqlite
  path: data/state.db
media:
  type: file
  path: data/media
  max_upload_size: 1024
  ttl_seconds: 60
adapters:
  - id: qq-main
    type: onebot
    config:
      mode: websocket
      endpoint: ws://127.0.0.1:3001
      token:
        env: ONEBOT_TOKEN
api:
  keys:
    - id: local
      secret:
        env: GATEWAY_API_KEY
      scopes: [events:read, commands:send, adapters:read]
"""


def write_config(tmp_path: Path, content: str = CONFIG) -> Path:
    """Write a test configuration.

    Args:
        tmp_path: Pytest temporary directory.
        content: YAML content.

    Returns:
        Configuration path.
    """
    path = tmp_path / "gateway.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_config_check_discovers_onebot_without_connecting(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path))
    resolver = EnvironmentSecretResolver(
        {"ONEBOT_TOKEN": "token", "GATEWAY_API_KEY": "api-key"}
    )

    result = check_config(config, resolver)

    assert "onebot" in result.adapter_types
    assert result.configured_instances == ("qq-main",)


def test_config_check_discovers_telegram_without_polling(tmp_path: Path) -> None:
    telegram = (
        CONFIG.replace("id: qq-main", "id: telegram-main")
        .replace(
            "type: onebot\n    config:\n      mode: websocket\n      endpoint: ws://127.0.0.1:3001",
            "type: telegram\n    config:",
        )
        .replace("ONEBOT_TOKEN", "TELEGRAM_TOKEN")
    )
    config = load_config(write_config(tmp_path, telegram))

    result = check_config(
        config,
        EnvironmentSecretResolver(
            {"TELEGRAM_TOKEN": "123:token", "GATEWAY_API_KEY": "api-key"}
        ),
    )

    assert "telegram" in result.adapter_types
    assert result.configured_instances == ("telegram-main",)


def test_config_rejects_duplicates_plaintext_and_missing_secrets(
    tmp_path: Path,
) -> None:
    duplicate = CONFIG.replace(
        "api:\n",
        "  - id: qq-main\n    type: onebot\n    config:\n      mode: websocket\n      endpoint: ws://127.0.0.1:3001\napi:\n",
    )
    with pytest.raises(ConfigError, match="duplicate adapter id"):
        load_config(write_config(tmp_path, duplicate))

    plaintext = CONFIG.replace("token:\n        env: ONEBOT_TOKEN", "token: secret")
    config = load_config(write_config(tmp_path, plaintext))
    with pytest.raises(ValueError, match="environment reference"):
        check_config(
            config,
            EnvironmentSecretResolver({"GATEWAY_API_KEY": "api-key"}),
        )

    config = load_config(write_config(tmp_path))
    with pytest.raises(ValueError, match="ONEBOT_TOKEN"):
        check_config(
            config,
            EnvironmentSecretResolver({"GATEWAY_API_KEY": "api-key"}),
        )


def test_host_builds_file_media_sqlite_state_and_health(tmp_path: Path) -> None:
    config_text = CONFIG.replace("  - id: qq-main", "  - id: qq-main").replace(
        "    type: onebot\n    config:",
        "    type: onebot\n    enabled: false\n    config:",
    )
    config = load_config(write_config(tmp_path, config_text))
    host = build_host(
        config,
        EnvironmentSecretResolver(
            {"ONEBOT_TOKEN": "token", "GATEWAY_API_KEY": "api-key"}
        ),
    )

    with TestClient(host.app) as client:
        response = client.get("/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert (tmp_path / "data" / "state.db").exists()
    assert (tmp_path / "data" / "media").is_dir()


def test_disabled_adapter_does_not_require_its_secret(tmp_path: Path) -> None:
    disabled = CONFIG.replace(
        "    type: onebot\n    config:",
        "    type: onebot\n    enabled: false\n    config:",
    )
    config = load_config(write_config(tmp_path, disabled))

    result = check_config(
        config,
        EnvironmentSecretResolver({"GATEWAY_API_KEY": "api-key"}),
    )

    assert result.configured_instances == ()


def test_cli_check_and_adapters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_config(tmp_path)
    monkeypatch.setenv("ONEBOT_TOKEN", "token")
    monkeypatch.setenv("GATEWAY_API_KEY", "api-key")

    assert main(["check", "-c", str(path)]) == 0
    assert "configuration valid" in capsys.readouterr().out
    assert main(["adapters", "-c", str(path)]) == 0
    assert "onebot\tconfigured" in capsys.readouterr().out

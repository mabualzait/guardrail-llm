from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
import pytest
from guardrail.cli import main


def test_cli_help(capsys):
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 0


def test_cli_run_configuration(tmp_path: Path, monkeypatch):
    yaml_config = tmp_path / "custom_guardrail.yaml"
    yaml_config.write_text(
        """
server:
  host: "127.0.0.1"
  port: 9191
upstream:
  base_url: "http://test-upstream:8000/v1"
"""
    )

    with patch("uvicorn.run") as mock_run:
        main([
            "run",
            "--config",
            str(yaml_config),
            "--host",
            "127.0.0.2",
            "--port",
            "9292",
            "--upstream",
            "http://override-upstream:8000/v1",
            "--workers",
            "2",
        ])

        assert mock_run.called
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["host"] == "127.0.0.2"
        assert call_kwargs["port"] == 9292
        assert call_kwargs["workers"] == 2

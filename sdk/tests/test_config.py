import pytest

import agentscope
from agentscope import Config, ConfigurationError, HTTPExporter
from agentscope.config import Config as ConfigClass
from agentscope.tracer import get_tracer


def test_defaults():
    cfg = Config()
    assert cfg.enabled is True
    assert cfg.service_name == "agentscope-app"
    assert cfg.endpoint is None


def test_from_env(monkeypatch):
    monkeypatch.setenv("AGENTSCOPE_SERVICE_NAME", "svc")
    monkeypatch.setenv("AGENTSCOPE_ENDPOINT", "http://localhost:5001")
    monkeypatch.setenv("AGENTSCOPE_API_KEY", "sk-test")
    monkeypatch.setenv("AGENTSCOPE_CONSOLE", "true")
    cfg = ConfigClass.from_env()
    assert cfg.service_name == "svc"
    assert cfg.endpoint == "http://localhost:5001"
    assert cfg.api_key == "sk-test"
    assert cfg.console is True


def test_configure_rejects_unknown_option():
    with pytest.raises(ConfigurationError):
        agentscope.configure(not_a_real_option=1)


def test_configure_endpoint_registers_http_exporter():
    agentscope.configure(endpoint="http://localhost:5001", api_key="k")
    exporters = get_tracer()._exporters
    assert any(isinstance(e, HTTPExporter) for e in exporters)


def test_configure_returns_config():
    cfg = agentscope.configure(service_name="my-app")
    assert cfg.service_name == "my-app"
    assert agentscope.get_config().service_name == "my-app"

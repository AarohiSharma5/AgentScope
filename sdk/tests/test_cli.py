import io
import json

import pytest

from agentscope.cli import main
from agentscope.cli.client import ApiClient, ApiError
from agentscope.cli.commands import CliError, Context, make_client
from agentscope.cli.console import Console
from agentscope.cli.parser import build_parser
from agentscope.cli.settings import Settings


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Point the CLI config at a temp file and clear inherited env."""
    cfg = tmp_path / "config.json"
    monkeypatch.setenv("AGENTSCOPE_CONFIG", str(cfg))
    for var in ("AGENTSCOPE_ENDPOINT", "AGENTSCOPE_API_KEY", "AGENTSCOPE_SERVICE_NAME",
                "AGENTSCOPE_DEFAULT_MODEL", "AGENTSCOPE_TIMEOUT"):
        monkeypatch.delenv(var, raising=False)
    return cfg


# -- console ----------------------------------------------------------------


def test_console_plaintext_when_color_off():
    buf = io.StringIO()
    c = Console(color=False, stream=buf)
    assert c.style("hi", "red") == "hi"  # no escape codes
    c.table(["ID", "Name"], [[1, "planner"], [2, "worker"]])
    out = buf.getvalue()
    assert "ID" in out and "planner" in out


def test_console_colors_when_enabled():
    c = Console(color=True, stream=io.StringIO())
    assert "\033[" in c.style("hi", "green")


# -- settings ---------------------------------------------------------------


def test_settings_roundtrip_and_mask(isolated_config):
    s = Settings.load()
    s.set("endpoint", "http://localhost:5001")
    s.set("api_key", "sk-supersecretvalue")
    s.save()

    reloaded = Settings.load()
    assert reloaded.endpoint == "http://localhost:5001"
    assert reloaded.api_key == "sk-supersecretvalue"
    masked = reloaded.as_dict()["api_key"]
    assert masked != "sk-supersecretvalue" and masked.startswith("sk-s")


def test_settings_env_overrides_file(isolated_config, monkeypatch):
    Settings.load().save()  # empty file
    monkeypatch.setenv("AGENTSCOPE_ENDPOINT", "http://env-host:9000")
    assert Settings.load().endpoint == "http://env-host:9000"


# -- parser / offline commands ----------------------------------------------


def test_parser_builds():
    parser = build_parser()
    args = parser.parse_args(["trace", "list", "--limit", "5"])
    assert args.command == "trace"
    assert args.trace_action == "list"
    assert args.limit == 5


def test_version_command(capsys):
    assert main(["version"]) == 0
    assert "agentscope-lite" in capsys.readouterr().out


def test_config_set_get_list(capsys):
    assert main(["config", "set", "endpoint", "http://localhost:5001"]) == 0
    main(["config", "get", "endpoint"])
    assert "http://localhost:5001" in capsys.readouterr().out
    assert main(["config", "list"]) == 0


def test_config_set_rejects_unknown_key():
    assert main(["config", "set", "bogus", "x"]) == 2  # CliError -> exit 2


def test_doctor_without_endpoint_passes(capsys):
    # No endpoint configured -> reachability is skipped, critical checks pass.
    assert main(["doctor"]) == 0
    assert "doctor" in capsys.readouterr().out.lower()


def test_make_client_requires_endpoint():
    ctx = Context(Console(color=False, stream=io.StringIO()), Settings.load())
    args = build_parser().parse_args(["status"])
    with pytest.raises(CliError):
        make_client(args, ctx)


# -- data commands against a fake server ------------------------------------


class _FakeResp:
    def __init__(self, status, payload, headers=None):
        self.status = status
        self._payload = payload
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._payload


def _install_fake_server(monkeypatch, routes):
    def fake_urlopen(req, timeout=None):
        url = req.full_url.split("?")[0]
        for path, (status, body) in routes.items():
            if url.endswith(path):
                payload = json.dumps(body).encode() if not isinstance(body, bytes) else body
                headers = {"Content-Disposition": 'attachment; filename="x.json"'} if isinstance(body, bytes) else {}
                return _FakeResp(status, payload, headers)
        return _FakeResp(404, json.dumps({"error": "not found"}).encode())

    monkeypatch.setattr("agentscope.cli.client.urllib.request.urlopen", fake_urlopen)


def test_trace_list_renders_table(monkeypatch, capsys):
    _install_fake_server(monkeypatch, {
        "/api/traces": (200, [
            {"id": 1, "model_name": "gpt-4o", "status": "success",
             "latency_ms": 120, "total_tokens": 30, "estimated_cost": 0.001},
        ]),
    })
    assert main(["--endpoint", "http://x", "trace", "list"]) == 0
    out = capsys.readouterr().out
    assert "gpt-4o" in out and "success" in out


def test_status_command(monkeypatch, capsys):
    _install_fake_server(monkeypatch, {
        "/api/stats": (200, {"total_requests": 10, "success_rate": 100.0}),
        "/api/stream/info": (200, {"subscribers": 2}),
    })
    assert main(["--endpoint", "http://x", "--json", "status"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["stats"]["total_requests"] == 10


def test_api_error_surfaces_message(monkeypatch, capsys):
    _install_fake_server(monkeypatch, {
        "/api/traces/999": (404, {"error": "trace not found"}),
    })
    assert main(["--endpoint", "http://x", "trace", "get", "999"]) == 2
    assert "trace not found" in capsys.readouterr().err


def test_client_ping(monkeypatch):
    _install_fake_server(monkeypatch, {"/api/stats": (200, {"ok": True})})
    assert ApiClient("http://x").ping() is True

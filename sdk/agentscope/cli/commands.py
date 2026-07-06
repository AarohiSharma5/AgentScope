"""Command handlers for the ``agentscope`` CLI.

Each ``cmd_*`` function takes the parsed ``args`` and a :class:`Context` and
returns a process exit code (0 = success). Handlers stay thin: they gather
input, call the server API (or local settings) and render results.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .. import __version__
from .client import ApiClient, ApiError
from .console import Console
from .settings import KNOWN_KEYS, Settings


class CliError(Exception):
    """A user-facing error; printed without a traceback."""


@dataclass
class Context:
    console: Console
    settings: Settings
    json_output: bool = False


# -- shared helpers ---------------------------------------------------------


def make_client(args, ctx: Context) -> ApiClient:
    endpoint = getattr(args, "endpoint", None) or ctx.settings.endpoint
    if not endpoint:
        raise CliError(
            "No server endpoint configured. Run 'agentscope init' or pass --endpoint URL."
        )
    api_key = getattr(args, "api_key", None) or ctx.settings.api_key
    return ApiClient(endpoint, api_key, ctx.settings.timeout)


def _emit(ctx: Context, data) -> None:
    """Print raw JSON (``--json``) — used by list/get commands."""
    ctx.console.json(data)


def _rows(payload):
    """Extract a list of records from a paginated or bare list payload."""
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"], payload.get("pagination")
    if isinstance(payload, list):
        return payload, None
    return [payload], None


# -- init / config ----------------------------------------------------------


def _wizard(args, ctx: Context, *, interactive: bool) -> None:
    c, s = ctx.console, ctx.settings
    endpoint_default = s.endpoint or "http://localhost:8000"
    if interactive:
        c.heading("AgentScope setup")
        endpoint = args.endpoint or c.ask("Server endpoint", endpoint_default)
        api_key = c.ask_secret("API key (optional)", s.api_key) if args.api_key is None else args.api_key
        service_name = c.ask("Service name", s.get("service_name") or "agentscope-app")
        default_model = c.ask("Default model (optional)", s.get("default_model") or "")
    else:
        endpoint = args.endpoint or endpoint_default
        api_key = args.api_key if args.api_key is not None else s.api_key
        service_name = getattr(args, "service_name", None) or s.get("service_name") or "agentscope-app"
        default_model = getattr(args, "default_model", None) or s.get("default_model")

    s.set("endpoint", endpoint)
    if api_key:
        s.set("api_key", api_key)
    s.set("service_name", service_name)
    if default_model:
        s.set("default_model", default_model)
    path = s.save()
    c.success(f"Saved configuration to {path}")

    client = ApiClient(endpoint, api_key or None, s.timeout)
    if client.ping():
        c.success(f"Server reachable at {endpoint}")
    else:
        c.warn(f"Server not reachable at {endpoint} (start it with 'agentscope start').")


def cmd_init(args, ctx: Context) -> int:
    _wizard(args, ctx, interactive=not args.yes)
    return 0


def cmd_config(args, ctx: Context) -> int:
    c, s = ctx.console, ctx.settings
    action = args.config_action
    if action in (None, "list", "show"):
        data = s.as_dict()
        if ctx.json_output:
            _emit(ctx, data)
        elif not data:
            c.info("No settings yet. Run 'agentscope init'.")
        else:
            for key in sorted(data):
                c.kv(key, data[key])
        return 0
    if action == "path":
        c.write(str(s.path))
        return 0
    if action == "get":
        c.write(str(s.get(args.key, "")))
        return 0
    if action == "set":
        if args.key not in KNOWN_KEYS:
            raise CliError(f"unknown key '{args.key}'. Known: {', '.join(sorted(KNOWN_KEYS))}")
        s.set(args.key, args.value)
        s.save()
        c.success(f"Set {args.key}")
        return 0
    if action == "unset":
        if s.unset(args.key):
            s.save()
            c.success(f"Unset {args.key}")
        else:
            c.warn(f"{args.key} was not set")
        return 0
    if action == "wizard":
        _wizard(args, ctx, interactive=True)
        return 0
    raise CliError(f"unknown config action '{action}'")


# -- diagnostics ------------------------------------------------------------


def cmd_version(args, ctx: Context) -> int:
    c = ctx.console
    if ctx.json_output:
        _emit(ctx, {"cli": __version__, "endpoint": ctx.settings.endpoint})
        return 0
    c.write(f"agentscope-lite {c.style(__version__, 'bold')}")
    c.dim(f"Python {sys.version.split()[0]} on {sys.platform}")
    if ctx.settings.endpoint:
        c.dim(f"endpoint: {ctx.settings.endpoint}")
    return 0


def cmd_doctor(args, ctx: Context) -> int:
    c, s = ctx.console, ctx.settings
    c.heading("AgentScope doctor")
    ok = True

    py_ok = sys.version_info >= (3, 9)
    _check(c, py_ok, "Python >= 3.9", f"found {sys.version.split()[0]}")

    _check(c, s.path.exists(), "Config file present", str(s.path), warn_only=True)
    _check(c, bool(s.endpoint), "Endpoint configured", s.endpoint or "unset", warn_only=True)
    _check(c, bool(s.api_key), "API key configured", "set" if s.api_key else "unset", warn_only=True)

    if s.endpoint:
        reachable = ApiClient(s.endpoint, s.api_key, s.timeout).ping()
        _check(c, reachable, "Server reachable", s.endpoint)
        ok = ok and reachable

    _check(c, _docker_available(), "Docker available (for 'start')", "optional", warn_only=True)

    if ok:
        c.success("All critical checks passed.")
    else:
        c.error("Some checks failed — see above.")
    return 0 if ok else 1


def cmd_status(args, ctx: Context) -> int:
    client = make_client(args, ctx)
    stats = client.get("/api/stats")
    info = None
    try:
        info = client.get("/api/stream/info")
    except ApiError:
        pass
    if ctx.json_output:
        _emit(ctx, {"stats": stats, "stream": info})
        return 0
    c = ctx.console
    c.heading("Platform status")
    for key in ("total_requests", "success_rate", "avg_latency_ms", "avg_total_tokens", "avg_cost"):
        if isinstance(stats, dict) and key in stats:
            c.kv(key, stats[key])
    if info:
        c.kv("subscribers", info.get("subscribers"))
    return 0


# -- server lifecycle -------------------------------------------------------


def cmd_start(args, ctx: Context) -> int:
    c = ctx.console
    compose = _find_compose()
    if compose is None:
        raise CliError(
            "Could not find docker-compose.yml. Run this from an AgentScope checkout, "
            "or clone https://github.com/AarohiSharma5/AgentScope and try again."
        )
    docker = _docker_cmd()
    if docker is None:
        raise CliError("Docker is not installed or not on PATH. Install Docker to use 'start'.")

    cmd = [*docker, "compose", "-f", str(compose), "up"]
    if args.build:
        cmd.append("--build")
    if args.detach:
        cmd.append("-d")
    c.info(f"Starting AgentScope: {' '.join(cmd)}")
    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:  # pragma: no cover - interactive
        return 0


# -- data: traces -----------------------------------------------------------


def cmd_trace(args, ctx: Context) -> int:
    client = make_client(args, ctx)
    if args.trace_action == "get":
        data = client.get(f"/api/traces/{args.id}")
        _emit(ctx, data)
        return 0
    data = client.get("/api/traces", params={"limit": args.limit})
    rows, _ = _rows(data)
    if ctx.json_output:
        _emit(ctx, data)
        return 0
    ctx.console.table(
        ["ID", "Model", "Status", "Latency(ms)", "Tokens", "Cost"],
        [[r.get("id"), r.get("model_name"), r.get("status"), r.get("latency_ms"),
          r.get("total_tokens"), r.get("estimated_cost")] for r in rows],
    )
    return 0


# -- data: replay / evaluate / compare --------------------------------------


def cmd_replay(args, ctx: Context) -> int:
    client = make_client(args, ctx)
    if args.replay_action == "list":
        data = client.get("/api/replays", params={"conversation_run_id": args.conversation, "limit": args.limit})
        return _print_list(ctx, data, ["ID", "Model", "Status", "Latency(ms)", "Cost"],
                           lambda r: [r.get("id"), r.get("replayed_model"), r.get("status"),
                                      r.get("latency_ms"), r.get("cost")])
    if args.replay_action == "get":
        _emit(ctx, client.get(f"/api/replays/{args.id}"))
        return 0
    # create
    body = {
        "conversation_run_id": args.conversation,
        "model": args.model,
        "temperature": args.temperature,
        "top_p": args.top_p,
        "system_prompt": args.system_prompt,
    }
    data = client.post("/api/replays", {k: v for k, v in body.items() if v is not None})
    ctx.console.success(f"Replay created (run #{data.get('id')})")
    _emit(ctx, data)
    return 0


def cmd_evaluate(args, ctx: Context) -> int:
    client = make_client(args, ctx)
    if args.evaluate_action == "list":
        data = client.get("/api/evaluations", params={"conversation_run_id": args.conversation, "limit": args.limit})
        return _print_list(ctx, data, ["ID", "Type", "Score", "Status"],
                           lambda r: [r.get("id"), r.get("evaluation_type"),
                                      r.get("overall_score"), r.get("status")])
    if args.evaluate_action == "get":
        _emit(ctx, client.get(f"/api/evaluations/{args.id}"))
        return 0
    body = {
        "conversation_run_id": args.conversation,
        "reference": args.reference,
        "expected_facts": args.expected_fact or None,
        "evaluation_type": args.type,
        "model_name": args.model,
    }
    data = client.post("/api/evaluations", {k: v for k, v in body.items() if v is not None})
    ctx.console.success(f"Evaluation created (run #{data.get('id')}, score {data.get('overall_score')})")
    _emit(ctx, data)
    return 0


def cmd_compare(args, ctx: Context) -> int:
    client = make_client(args, ctx)
    if args.compare_action == "list":
        data = client.get("/api/comparisons", params={"conversation_run_id": args.conversation, "limit": args.limit})
        return _print_list(ctx, data, ["ID", "Model A", "Model B", "Winner"],
                           lambda r: [r.get("id"), r.get("model_a"), r.get("model_b"), r.get("winner")])
    body = {
        "conversation_run_id": args.conversation,
        "models": args.model,
        "baseline_model": args.baseline,
        "evaluate": args.evaluate,
    }
    data = client.post("/api/comparisons", {k: v for k, v in body.items() if v is not None})
    ctx.console.success(f"Comparison complete — winner: {data.get('winner')}")
    _emit(ctx, data)
    return 0


# -- data: plugins / providers ----------------------------------------------


def cmd_plugins(args, ctx: Context) -> int:
    client = make_client(args, ctx)
    action = args.plugins_action
    if action in (None, "list"):
        data = client.get("/api/plugins")
        rows, _ = _rows(data)
        if ctx.json_output:
            return _emit(ctx, data) or 0
        ctx.console.table(
            ["Name", "Version", "State", "Capabilities"],
            [[p.get("name"), p.get("version"), p.get("state"),
              ",".join(p.get("capabilities", []))] for p in rows],
        )
        return 0
    if action == "extensions":
        _emit(ctx, client.get("/api/plugins/extensions", params={"capability": args.capability}))
        return 0
    if action == "enable":
        client.post(f"/api/plugins/{args.name}/enable")
        ctx.console.success(f"Enabled {args.name}")
        return 0
    if action == "disable":
        client.post(f"/api/plugins/{args.name}/disable",
                    params={"cascade": "false" if args.no_cascade else None})
        ctx.console.success(f"Disabled {args.name}")
        return 0
    if action == "reload":
        client.post(f"/api/plugins/{args.name}/reload")
        ctx.console.success(f"Reloaded {args.name}")
        return 0
    if action == "uninstall":
        client.delete(f"/api/plugins/{args.name}")
        ctx.console.success(f"Uninstalled {args.name}")
        return 0
    raise CliError(f"unknown plugins action '{action}'")


def cmd_providers(args, ctx: Context) -> int:
    client = make_client(args, ctx)
    action = args.providers_action
    if action in (None, "list"):
        data = client.get("/api/providers", params={"kind": args.kind, "capability": args.capability})
        providers = data.get("providers", []) if isinstance(data, dict) else data
        if ctx.json_output:
            return _emit(ctx, data) or 0
        ctx.console.table(
            ["Name", "Kind", "Capabilities"],
            [[p.get("name"), p.get("kind"), ",".join(p.get("capabilities", []))] for p in providers],
        )
        return 0
    if action == "capabilities":
        _emit(ctx, client.get("/api/providers/capabilities"))
        return 0
    if action == "info":
        _emit(ctx, client.get(f"/api/providers/{args.name}"))
        return 0
    if action == "health":
        try:
            data = client.get(f"/api/providers/{args.name}/health")
        except ApiError as exc:
            if exc.status == 503 and isinstance(exc.details, dict):
                data = exc.details
            else:
                raise
        _emit(ctx, data)
        return 0
    raise CliError(f"unknown providers action '{action}'")


# -- data: export / import --------------------------------------------------


def cmd_export(args, ctx: Context) -> int:
    client = make_client(args, ctx)
    if args.export_action == "formats":
        _emit(ctx, client.get("/api/export/formats"))
        return 0
    if args.export_action == "kinds":
        _emit(ctx, client.get("/api/export/kinds"))
        return 0

    if args.export_action == "analytics":
        content, filename = client.download("/api/export/analytics", params={"format": args.format})
    else:  # entity export: kind + id
        content, filename = client.download(
            f"/api/export/{args.kind}/{args.id}", params={"format": args.format}
        )
    return _write_download(ctx, content, filename, args.out)


def cmd_import(args, ctx: Context) -> int:
    client = make_client(args, ctx)
    path = Path(args.file).expanduser()
    if not path.exists():
        raise CliError(f"file not found: {path}")
    data = path.read_bytes()
    params = {"format": args.format}

    if args.inspect:
        _emit(ctx, client.post_raw("/api/import/inspect", data, params=params))
        return 0
    if args.replay:
        params.update({"model": args.model, "temperature": args.temperature})
        result = client.post_raw("/api/import/replay", data, params=params)
        ctx.console.success("Imported and replayed.")
        _emit(ctx, result)
        return 0
    result = client.post_raw("/api/import", data, params=params)
    ctx.console.success("Imported bundle into the platform.")
    _emit(ctx, result)
    return 0


# -- small internal helpers -------------------------------------------------


def _print_list(ctx: Context, data, headers, row_fn) -> int:
    if ctx.json_output:
        _emit(ctx, data)
        return 0
    rows, _ = _rows(data)
    ctx.console.table(headers, [row_fn(r) for r in rows])
    return 0


def _write_download(ctx: Context, content: bytes, filename: str, out: Optional[str]) -> int:
    target = Path(out).expanduser() if out else Path(filename)
    target.write_bytes(content)
    ctx.console.success(f"Saved {len(content)} bytes to {target}")
    return 0


def _check(console: Console, ok: bool, label: str, detail: str = "", warn_only: bool = False) -> None:
    if ok:
        console.success(f"{label} {console.style('(' + detail + ')', 'dim') if detail else ''}")
    elif warn_only:
        console.warn(f"{label} — {detail}")
    else:
        console.error(f"{label} — {detail}")


def _docker_cmd() -> Optional[list]:
    if shutil.which("docker"):
        return ["docker"]
    return None


def _docker_available() -> bool:
    return _docker_cmd() is not None


def _find_compose() -> Optional[Path]:
    """Walk up from the cwd looking for a docker-compose file."""
    for directory in [Path.cwd(), *Path.cwd().parents]:
        for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml"):
            candidate = directory / name
            if candidate.exists():
                return candidate
    return None

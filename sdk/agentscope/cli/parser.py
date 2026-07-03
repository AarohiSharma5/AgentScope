"""Builds the ``agentscope`` argparse command tree with rich help text."""
from __future__ import annotations

import argparse

from .. import __version__
from . import commands as C

_EPILOG = """\
examples:
  agentscope init                        run the interactive configuration wizard
  agentscope doctor                      check your environment and connectivity
  agentscope status                      show live platform metrics
  agentscope trace list --limit 20       list recent request traces
  agentscope replay create --conversation 5 --model gpt-4o
  agentscope evaluate run --conversation 5 --reference "42"
  agentscope compare run --conversation 5 --model gpt-4o --model claude-3
  agentscope plugins list
  agentscope providers health openai
  agentscope export conversation 5 --format otel --out trace.json
  agentscope import bundle.json --replay --model gpt-4o
  agentscope                             start the interactive shell

Run 'agentscope <command> -h' for command-specific help.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentscope",
        description="AgentScope — observability CLI for AI agents, tools and workflows.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"agentscope-lite {__version__}")
    # Global options (place before the command).
    parser.add_argument("--endpoint", metavar="URL", help="AgentScope server URL (overrides config).")
    parser.add_argument("--api-key", dest="api_key", metavar="KEY", default=None,
                        help="API key for the server (overrides config).")
    parser.add_argument("--json", dest="json_output", action="store_true",
                        help="Output raw JSON instead of formatted tables.")
    parser.add_argument("--timeout", type=float, metavar="SECS", help="HTTP timeout in seconds.")
    color = parser.add_mutually_exclusive_group()
    color.add_argument("--no-color", dest="no_color", action="store_true", help="Disable colored output.")
    color.add_argument("--color", dest="force_color", action="store_true", help="Force colored output.")

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    _add_init(sub)
    _add_config(sub)
    _add_start(sub)
    _add_trace(sub)
    _add_replay(sub)
    _add_evaluate(sub)
    _add_compare(sub)
    _add_plugins(sub)
    _add_providers(sub)
    _add_export(sub)
    _add_import(sub)
    _add_status(sub)
    _add_doctor(sub)
    _add_version(sub)
    _add_interactive(sub)

    return parser


# -- command builders -------------------------------------------------------


def _add_init(sub) -> None:
    p = sub.add_parser("init", help="Configure the CLI (interactive wizard).",
                       description="Create or update the CLI configuration. Interactive by default; "
                                   "pass --yes for non-interactive setup using flags/defaults.")
    p.add_argument("--service-name", dest="service_name", help="Logical service name.")
    p.add_argument("--default-model", dest="default_model", help="Default model recorded on LLM spans.")
    p.add_argument("-y", "--yes", action="store_true", help="Skip prompts; accept defaults/flags.")
    p.set_defaults(func=C.cmd_init)


def _add_config(sub) -> None:
    p = sub.add_parser("config", help="View or edit CLI configuration.",
                       description="Get, set and inspect persisted CLI settings.")
    p.set_defaults(func=C.cmd_config, config_action=None)
    cs = p.add_subparsers(dest="config_action", metavar="<action>")
    cs.add_parser("list", help="Show all settings.")
    cs.add_parser("show", help="Alias for list.")
    cs.add_parser("path", help="Print the config file path.")
    g = cs.add_parser("get", help="Get one setting.")
    g.add_argument("key")
    st = cs.add_parser("set", help="Set one setting.")
    st.add_argument("key")
    st.add_argument("value")
    un = cs.add_parser("unset", help="Remove one setting.")
    un.add_argument("key")
    cs.add_parser("wizard", help="Run the interactive setup wizard.")


def _add_start(sub) -> None:
    p = sub.add_parser("start", help="Start the AgentScope platform (docker compose).",
                       description="Launch the full platform via docker compose, discovered by "
                                   "walking up from the current directory.")
    p.add_argument("--build", action="store_true", help="Rebuild images before starting.")
    p.add_argument("-d", "--detach", action="store_true", help="Run in the background.")
    p.set_defaults(func=C.cmd_start)


def _add_trace(sub) -> None:
    p = sub.add_parser("trace", help="Inspect request traces.",
                       description="List recent request traces or fetch one by id.")
    p.set_defaults(func=C.cmd_trace, trace_action="list", limit=50)
    ts = p.add_subparsers(dest="trace_action", metavar="<action>")
    ls = ts.add_parser("list", help="List recent traces.")
    ls.add_argument("--limit", type=int, default=50, help="Max rows (default 50).")
    gt = ts.add_parser("get", help="Show one trace by id.")
    gt.add_argument("id", type=int)


def _add_replay(sub) -> None:
    p = sub.add_parser("replay", help="List or run replays.",
                       description="Re-run a traced conversation under new parameters, or browse replays.")
    p.set_defaults(func=C.cmd_replay, replay_action="list", conversation=None, limit=20)
    rs = p.add_subparsers(dest="replay_action", metavar="<action>")
    ls = rs.add_parser("list", help="List replay runs.")
    ls.add_argument("--conversation", type=int, help="Filter by original conversation id.")
    ls.add_argument("--limit", type=int, default=20)
    gt = rs.add_parser("get", help="Show one replay run.")
    gt.add_argument("id", type=int)
    cr = rs.add_parser("create", help="Create and run a replay.")
    cr.add_argument("--conversation", type=int, required=True, help="Conversation run id to replay.")
    cr.add_argument("--model", help="Override the model.")
    cr.add_argument("--temperature", type=float)
    cr.add_argument("--top-p", dest="top_p", type=float)
    cr.add_argument("--system-prompt", dest="system_prompt", help="Override the system prompt.")


def _add_evaluate(sub) -> None:
    p = sub.add_parser("evaluate", help="List or run evaluations.",
                       description="Score a conversation with the built-in evaluators, or browse runs.")
    p.set_defaults(func=C.cmd_evaluate, evaluate_action="list", conversation=None, limit=20)
    es = p.add_subparsers(dest="evaluate_action", metavar="<action>")
    ls = es.add_parser("list", help="List evaluation runs.")
    ls.add_argument("--conversation", type=int)
    ls.add_argument("--limit", type=int, default=20)
    gt = es.add_parser("get", help="Show one evaluation run.")
    gt.add_argument("id", type=int)
    rn = es.add_parser("run", help="Run an evaluation.")
    rn.add_argument("--conversation", type=int, required=True, help="Conversation run id to evaluate.")
    rn.add_argument("--reference", help="Reference/expected answer.")
    rn.add_argument("--expected-fact", dest="expected_fact", action="append",
                    help="An expected fact (repeatable).")
    rn.add_argument("--type", help="Evaluation type label.")
    rn.add_argument("--model", dest="model", help="Model name recorded on the run.")


def _add_compare(sub) -> None:
    p = sub.add_parser("compare", help="List or run model comparisons.",
                       description="Run one conversation against multiple models and compare them.")
    p.set_defaults(func=C.cmd_compare, compare_action="list", conversation=None, limit=20)
    cs = p.add_subparsers(dest="compare_action", metavar="<action>")
    ls = cs.add_parser("list", help="List comparisons.")
    ls.add_argument("--conversation", type=int)
    ls.add_argument("--limit", type=int, default=20)
    rn = cs.add_parser("run", help="Run a comparison.")
    rn.add_argument("--conversation", type=int, required=True, help="Conversation run id.")
    rn.add_argument("--model", action="append", required=True,
                    help="A model to compare (repeat for each).")
    rn.add_argument("--baseline", help="Baseline model name.")
    rn.add_argument("--evaluate", action="store_true", help="Also evaluate each candidate.")


def _add_plugins(sub) -> None:
    p = sub.add_parser("plugins", help="Manage platform plugins.",
                       description="List plugins and manage their lifecycle.")
    p.set_defaults(func=C.cmd_plugins, plugins_action="list", capability=None)
    ps = p.add_subparsers(dest="plugins_action", metavar="<action>")
    ps.add_parser("list", help="List installed plugins.")
    ex = ps.add_parser("extensions", help="List contributed extensions.")
    ex.add_argument("--capability", help="Filter by capability.")
    for name, helptext in (("enable", "Enable a plugin."), ("reload", "Reload a plugin."),
                           ("uninstall", "Uninstall a plugin.")):
        q = ps.add_parser(name, help=helptext)
        q.add_argument("name")
    dis = ps.add_parser("disable", help="Disable a plugin.")
    dis.add_argument("name")
    dis.add_argument("--no-cascade", dest="no_cascade", action="store_true",
                     help="Do not cascade to dependents.")


def _add_providers(sub) -> None:
    p = sub.add_parser("providers", help="Discover LLM/embedding providers.",
                       description="List providers, capabilities, and run live health checks.")
    p.set_defaults(func=C.cmd_providers, providers_action="list", kind=None, capability=None)
    ps = p.add_subparsers(dest="providers_action", metavar="<action>")
    ls = ps.add_parser("list", help="List providers.")
    ls.add_argument("--kind", help="Filter by kind (llm, embedding, …).")
    ls.add_argument("--capability", help="Filter by capability.")
    ps.add_parser("capabilities", help="Show capability → providers map.")
    inf = ps.add_parser("info", help="Show one provider's description.")
    inf.add_argument("name")
    hl = ps.add_parser("health", help="Live health check for a provider.")
    hl.add_argument("name")


def _add_export(sub) -> None:
    p = sub.add_parser("export", help="Export traces and analytics.",
                       description="Export platform data in JSON, CSV, OpenTelemetry, SQLite, "
                                   "Postgres, Zip or Trace Bundle formats.")
    p.set_defaults(func=C.cmd_export, format="json", out=None)
    es = p.add_subparsers(dest="export_action", metavar="<action>", required=True)
    es.add_parser("formats", help="List available export formats.")
    es.add_parser("kinds", help="List exportable/importable kinds.")
    an = es.add_parser("analytics", help="Export the analytics snapshot.")
    _export_io(an)
    for kind in ("conversation", "workflow", "replay", "evaluation"):
        ek = es.add_parser(kind, help=f"Export a {kind} by id.")
        ek.add_argument("id", type=int)
        _export_io(ek)
        ek.set_defaults(kind=kind)


def _export_io(parser) -> None:
    parser.add_argument("--format", default="json",
                        help="Format: json, csv, otel, sqlite, postgres, zip, bundle (default json).")
    parser.add_argument("--out", help="Output file (defaults to the server-suggested name).")


def _add_import(sub) -> None:
    p = sub.add_parser("import", help="Import a bundle into the platform.",
                       description="Reconstruct an exported bundle into the platform, inspect it, "
                                   "or import-and-replay a conversation.")
    p.add_argument("file", help="Path to the exported bundle file.")
    p.add_argument("--format", help="Override auto-detected format.")
    p.add_argument("--inspect", action="store_true", help="Parse and verify only; do not write.")
    p.add_argument("--replay", action="store_true", help="Import a conversation and replay it.")
    p.add_argument("--model", help="Model override when replaying.")
    p.add_argument("--temperature", type=float, help="Temperature override when replaying.")
    p.set_defaults(func=C.cmd_import)


def _add_status(sub) -> None:
    p = sub.add_parser("status", help="Show platform status/metrics.",
                       description="Query the server for headline metrics and live subscriber count.")
    p.set_defaults(func=C.cmd_status)


def _add_doctor(sub) -> None:
    p = sub.add_parser("doctor", help="Diagnose the environment and connectivity.",
                       description="Run environment and connectivity checks with colored results.")
    p.set_defaults(func=C.cmd_doctor)


def _add_version(sub) -> None:
    p = sub.add_parser("version", help="Show the CLI/SDK version.",
                       description="Print the installed agentscope-lite version and environment.")
    p.set_defaults(func=C.cmd_version)


def _add_interactive(sub) -> None:
    p = sub.add_parser("interactive", aliases=["shell"],
                       help="Start the interactive shell.",
                       description="Launch a REPL that accepts the same commands.")
    p.set_defaults(func=None, command="interactive")

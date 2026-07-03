"""Entry point and interactive shell for the ``agentscope`` CLI."""
from __future__ import annotations

import shlex
import sys
from typing import List, Optional

from .client import ApiError
from .commands import CliError, Context
from .console import Console
from .parser import build_parser
from .settings import Settings


def _color_preference(args) -> Optional[bool]:
    if getattr(args, "no_color", False):
        return False
    if getattr(args, "force_color", False):
        return True
    return None


def _build_context(args) -> Context:
    settings = Settings.load()
    if getattr(args, "timeout", None):
        settings.set("timeout", args.timeout)
    console = Console(color=_color_preference(args))
    return Context(console, settings, json_output=getattr(args, "json_output", False))


def _dispatch(args, ctx: Context) -> int:
    func = getattr(args, "func", None)
    if func is None:
        return 1
    try:
        return func(args, ctx) or 0
    except CliError as exc:
        ctx.console.error(str(exc))
        return 2
    except ApiError as exc:
        detail = f" ({exc.details})" if exc.details else ""
        ctx.console.error(f"{exc}{detail}")
        return 2
    except KeyboardInterrupt:  # pragma: no cover - interactive
        ctx.console.write("")
        return 130


def _run_interactive(parser, ctx: Context) -> int:
    ctx.console.heading("AgentScope interactive shell")
    ctx.console.dim("Type a command (e.g. 'status'), 'help', or 'exit'.")
    while True:
        try:
            line = input(ctx.console.style("agentscope> ", "cyan")).strip()
        except (EOFError, KeyboardInterrupt):
            ctx.console.write("")
            break
        if not line:
            continue
        if line in {"exit", "quit"}:
            break
        if line in {"help", "?"}:
            parser.print_help()
            continue
        try:
            parts = shlex.split(line)
        except ValueError as exc:
            ctx.console.error(str(exc))
            continue
        try:
            args = parser.parse_args(parts)
        except SystemExit:
            # argparse already printed help/errors; keep the shell alive.
            continue
        if getattr(args, "command", None) in (None, "interactive"):
            continue
        ctx.json_output = getattr(args, "json_output", ctx.json_output)
        _dispatch(args, ctx)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """Program entry point (installed as the ``agentscope`` command)."""
    parser = build_parser()
    args = parser.parse_args(argv)
    ctx = _build_context(args)

    command = getattr(args, "command", None)

    if command == "interactive":
        return _run_interactive(parser, ctx)

    if command is None:
        # No subcommand: drop into the shell on a TTY, else show help.
        if sys.stdin.isatty() and sys.stdout.isatty():
            return _run_interactive(parser, ctx)
        parser.print_help()
        return 1

    return _dispatch(args, ctx)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

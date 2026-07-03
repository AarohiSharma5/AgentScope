# CLI Reference — `agentscope`

Installing `agentscope-lite` provides the `agentscope` command (and
`python -m agentscope`). It is built on the Python standard library only
(`argparse` + `urllib`), with colored output, an interactive mode and a
configuration wizard, and works cross-platform.

```bash
pip install agentscope-lite
agentscope version
```

## Global flags

| Flag | Purpose |
| ---- | ------- |
| `--endpoint URL` | AgentScope server URL (overrides config). |
| `--api-key KEY` | API key / bearer token. |
| `--json` | Emit raw JSON instead of formatted tables. |
| `--timeout SECONDS` | HTTP timeout. |
| `--color` / `--no-color` | Force or disable color (auto on TTYs; respects `NO_COLOR`). |

Run `agentscope <command> -h` for per-command help.

## Commands

| Command | Description |
| ------- | ----------- |
| `init` | Interactive configuration wizard (endpoint, API key, defaults). |
| `start` | Launch the platform via `docker compose` (auto-detects the compose file). |
| `status` | Show live platform metrics from the server. |
| `doctor` | Diagnose environment + connectivity to the server. |
| `version` | Print the SDK/CLI version. |
| `config` | Manage persistent config (`list`, `get`, `set`, `unset`, `path`, `wizard`). |
| `trace` | Work with request traces (`list`, ...). |
| `replay` | Create/list replays. |
| `evaluate` | Run/list evaluations. |
| `compare` | Compare a conversation across models. |
| `plugins` | List/enable/disable/reload plugins. |
| `providers` | List providers; check capabilities and health. |
| `export` | Export a conversation/workflow/replay/evaluation/analytics. |
| `import` | Import a bundle; optionally replay from it. |

## Configuration

Settings persist to `~/.agentscope/config.json` (override with
`AGENTSCOPE_CONFIG` or `AGENTSCOPE_HOME`). Precedence: CLI flags → environment
variables → config file. API keys are masked in output.

```bash
agentscope init                              # guided setup
agentscope config set endpoint http://localhost:5001
agentscope config set api_key as_xxx
agentscope config list
agentscope config path
```

## Everyday usage

```bash
agentscope doctor                            # check environment + connectivity
agentscope status                            # live platform metrics
agentscope trace list --limit 20             # recent request traces

agentscope replay create --conversation 5 --model gpt-4o-mini --temperature 0.2
agentscope replay list

agentscope evaluate run --conversation 5 --reference "42"
agentscope compare run --conversation 5 --model gpt-4o --model claude-3-5-sonnet

agentscope plugins list
agentscope plugins enable sample-tools

agentscope providers list
agentscope providers health openai

agentscope export conversation 5 --format otel --out trace.json
agentscope import bundle.json --replay --model gpt-4o

agentscope start                             # docker compose up
```

## Interactive shell

Run `agentscope` with no arguments (or `agentscope interactive`) to enter a REPL
where you can issue the same commands without the `agentscope` prefix:

```
$ agentscope
agentscope> status
agentscope> trace list --limit 5
agentscope> help
agentscope> exit
```

## See also

- [SDK reference](sdk.md) — the library behind the CLI.
- [REST API](rest-api.md) — the endpoints the CLI calls.
- [Deployment](../deployment.md) — configure the server the CLI talks to.

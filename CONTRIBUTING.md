# Contributing to AgentScope

Thanks for your interest in improving AgentScope! This project is an open-source
observability platform for AI agents, tools and workflows, released under the
[MIT License](LICENSE). Contributions of all kinds — bug reports, features, docs,
tests, examples — are welcome.

By participating you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

## Ways to contribute

- **Report a bug** — open a [bug report](https://github.com/AarohiSharma5/AgentScope/issues/new/choose).
- **Request a feature** — open a feature request issue.
- **Fix / build something** — comment on an issue (or open one) so we can avoid
  duplicate work, then send a pull request.
- **Improve docs** — everything under `docs/` and the READMEs is fair game.

## Project layout

```
backend/    Flask REST API, services, models, engines (SQLAlchemy)
frontend/   React + Vite + TailwindCSS dashboard
sdk/        agentscope-lite Python SDK + CLI (dependency-free)
docs/       Documentation site (Markdown + Mermaid)
examples/   Runnable example programs
```

See [docs/reference/architecture.md](docs/reference/architecture.md) for the full
picture.

## Development setup

### Backend
```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
python run.py                                        # starts on http://localhost:5000
```

By default the backend uses a zero-config SQLite database. Point `DATABASE_URL`
at PostgreSQL to develop against it.

### Frontend
```bash
cd frontend
npm ci
npm run dev        # http://localhost:5173
```

### SDK / CLI
```bash
cd sdk
pip install -e .
agentscope --help
```

### Everything, via Docker
```bash
docker compose up --build
```

## Running the checks

Please make sure the relevant checks pass before opening a PR. CI runs all of
these on Linux, macOS and Windows.

```bash
# Backend tests
cd backend && python -m pytest

# SDK tests
cd sdk && python -m pytest

# Frontend tests + build
cd frontend && npx vitest run && npm run build

# Lint (Python)
ruff check backend/app backend/tests sdk/agentscope

# Security scan (Python)
bandit -q -r backend/app sdk/agentscope
```

## Coding standards

- **Python**: PEP 8, type hints on public functions, docstrings on modules,
  classes and non-trivial functions. Keep business logic in the **service /
  engine layer** — routes stay thin and never touch the SQLAlchemy session
  directly. Lint with Ruff (`ruff.toml` is the source of truth).
- **JavaScript/React**: functional components and hooks, TailwindCSS for styling,
  small reusable components, no duplicated markup. Prefer memoization for
  frequently re-rendered lists.
- **Compatibility**: changes must work on **both SQLite and PostgreSQL** and must
  preserve **backward compatibility** — additive changes over breaking ones.
- **Tests**: add or update tests for any behavior change. New endpoints need API
  tests; new engine/service logic needs unit tests.
- **Comments**: explain *why*, not *what*. Don't narrate obvious code.

## Commit & pull request process

1. Fork and create a topic branch (`feat/…`, `fix/…`, `docs/…`).
2. Make focused commits with clear messages (we loosely follow
   [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`,
   `docs:`, `perf:`, `test:`, `chore:`).
3. Ensure the checks above pass and update docs/CHANGELOG where relevant.
4. Open a PR against `main` using the PR template, describing the change and how
   you tested it. Link any related issue.
5. A maintainer will review; please be responsive to feedback. CI must be green
   before merge.

## Reporting security issues

Please **do not** open a public issue for security vulnerabilities. Follow the
process in [SECURITY.md](SECURITY.md).

## License

By contributing, you agree that your contributions will be licensed under the
MIT License that covers this project.

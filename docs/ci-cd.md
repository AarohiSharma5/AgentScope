# CI/CD

AgentScope uses **GitHub Actions** for continuous integration and delivery. The
workflows live in [`.github/workflows/`](../.github/workflows).

## Workflows

| Workflow | Trigger | What it does |
| -------- | ------- | ------------ |
| [`ci.yml`](../.github/workflows/ci.yml) | push, PR, manual | Lint, format check, security scan, tests + coverage, frontend build, Docker builds. |
| [`codeql.yml`](../.github/workflows/codeql.yml) | push, PR, weekly | CodeQL SAST for Python and JavaScript/TypeScript. |
| [`release.yml`](../.github/workflows/release.yml) | tag `v*.*.*`, manual | Build/publish the SDK to PyPI, push Docker images to GHCR, create a GitHub Release with changelog + artifacts. |

Dependency updates are automated via [Dependabot](../.github/dependabot.yml)
(pip, npm, Docker and GitHub Actions).

## CI (`ci.yml`)

Runs on every push and pull request. Jobs:

- **Lint & format** — `ruff check` (build-failing) and `ruff format --check`
  (advisory diff). Configured by [`ruff.toml`](../ruff.toml).
- **Security scan** — `bandit` (gates on high severity + high confidence),
  plus a full Bandit report and `pip-audit` dependency audit uploaded as
  advisory artifacts.
- **Backend tests** — pytest with coverage across a matrix of
  **Linux / macOS / Windows** × Python **3.10 / 3.11 / 3.12**. Coverage is
  uploaded as an artifact and to Codecov.
- **SDK tests** — pytest with coverage across the same OSes × Python
  **3.9 / 3.10 / 3.11 / 3.12**.
- **Frontend** — `npm ci`, `npm test` (Vitest), `npm run build`; the build is
  uploaded as an artifact.
- **Docker image build** — builds the backend and frontend images with Buildx
  (validates the Dockerfiles; images are pushed only by the release workflow).
- **CI success** — a gate job that fails unless every required job passed.

**Test failures fail the build.** Dependency and formatting audits are advisory
so upstream CVEs or style drift don't block unrelated work; they surface as
reports/artifacts instead.

**Dependency caching** is enabled everywhere: pip (`setup-python` cache), npm
(`setup-node` cache) and Docker layers (`type=gha` Buildx cache).

## Releases (`release.yml`)

Two ways to cut a release:

1. **Push a tag** — `git tag v1.0.1 && git push origin v1.0.1`.
2. **Manual dispatch** — run the *Release* workflow from the Actions tab with a
   `version` input; it creates and pushes the tag for you.

The workflow then:

1. Resolves the version and ensures the tag exists.
2. Builds the SDK (`python -m build`) and validates it (`twine check`).
3. Publishes the SDK to **PyPI** (Trusted Publishing via OIDC, or a
   `PYPI_API_TOKEN` secret). This step is non-blocking so a release still
   succeeds before PyPI is configured.
4. Builds and pushes **Docker images** to **GHCR**
   (`ghcr.io/<owner>/agentscope-backend` and `-frontend`), tagged with the
   version and `latest`.
5. Creates a **GitHub Release**: extracts the matching section from
   [`CHANGELOG.md`](../CHANGELOG.md), appends auto-generated notes, and attaches
   the built `sdist`/`wheel`.

## Required configuration

| Secret / setting | Used by | Required? |
| ---------------- | ------- | --------- |
| `GITHUB_TOKEN` (built-in) | GHCR push, release, tagging | Automatic |
| PyPI Trusted Publisher **or** `PYPI_API_TOKEN` | PyPI publish | For publishing |
| `CODECOV_TOKEN` | Codecov upload | Optional (public repos) |

## Running the checks locally

```bash
# Lint + format (matches CI)
pip install -r backend/requirements-dev.txt
ruff check backend sdk
ruff format --check backend sdk

# Security
bandit -r backend/app sdk/agentscope --severity-level high --confidence-level high
pip-audit -r backend/requirements.txt

# Tests + coverage
cd backend && pytest --cov=app --cov-report=term-missing
cd ../sdk && pytest --cov=agentscope --cov-report=term-missing

# Frontend
cd ../frontend && npm ci && npm test && npm run build
```

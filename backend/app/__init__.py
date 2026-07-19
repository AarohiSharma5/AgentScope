"""Application factory for the AgentScope backend."""
import atexit
import logging
import sqlite3

from dotenv import load_dotenv
from flask import Flask, request
from flask_cors import CORS
from sqlalchemy import event

from .config import Config
from .errors import register_error_handlers
from .extensions import db
from .version import API_VERSION

load_dotenv()

# Guards a single process-wide atexit registration across repeated create_app
# calls (tests build many apps; the managers below are process singletons).
_SHUTDOWN_ATEXIT_REGISTERED = False


def _register_lifecycle_shutdown(app: Flask) -> None:
    """Coordinate graceful teardown of the process-wide background managers.

    The job manager, live-trace broadcaster and evaluation executors each own
    threads that must be released when a worker exits or reloads; their
    ``shutdown()`` methods existed but were never called. This registers a single
    idempotent shutdown that closes all three, wires it to :mod:`atexit`
    (covering normal interpreter/worker exit), and also exposes it as
    ``app.extensions["shutdown"]`` so a gunicorn ``worker_exit`` hook can invoke
    it explicitly for a hard, timely teardown.
    """
    global _SHUTDOWN_ATEXIT_REGISTERED

    def _shutdown() -> None:
        from .evaluation.engine import shutdown_all_engines
        from .jobs import job_manager
        from .streaming.manager import live_trace_manager

        # At interpreter exit the logging streams may already be closed; don't let
        # a teardown log line raise (or dump a spurious "Logging error").
        logging.raiseExceptions = False

        for name, fn in (
            ("job manager", lambda: job_manager.shutdown(wait=False)),
            ("live trace manager", live_trace_manager.shutdown),
            ("evaluation executors", shutdown_all_engines),
        ):
            try:
                fn()
            except Exception:  # noqa: BLE001 - teardown must never raise
                logging.getLogger("agentscope").exception(
                    "error shutting down %s", name
                )

    app.extensions["shutdown"] = _shutdown
    if not _SHUTDOWN_ATEXIT_REGISTERED:
        atexit.register(_shutdown)
        _SHUTDOWN_ATEXIT_REGISTERED = True


def _configure_stream_broker(app: Flask) -> None:
    """Attach the configured cross-worker streaming broker (Redis) if any.

    No-op when ``STREAM_BROKER_URL`` is unset (single-process in-memory fan-out,
    the default). Any failure falls back to in-process rather than blocking boot.
    """
    url = app.config.get("STREAM_BROKER_URL")
    if not url:
        return
    from .streaming.broker import build_broker
    from .streaming.manager import live_trace_manager

    broker = build_broker(url)
    live_trace_manager.use_broker(broker)


def _configure_logging() -> None:
    """Configure a single ``agentscope`` logger (idempotent across reloads)."""
    logger = logging.getLogger("agentscope")
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def _enable_sqlite_foreign_keys(app: Flask) -> None:
    """Enforce foreign keys on SQLite so ``ON DELETE CASCADE`` behaves like Postgres."""
    with app.app_context():
        if db.engine.dialect.name != "sqlite":
            return

        @event.listens_for(db.engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _connection_record):
            if isinstance(dbapi_connection, sqlite3.Connection):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()


# Secret values that ship as documentation placeholders. Booting with auth on
# while still using any of these means JWTs are trivially forgeable.
_DEFAULT_SECRETS = frozenset({None, "", "dev-secret-key", "change-me-in-production"})

# API prefixes the app answers on: the versioned contract and its unversioned
# alias. Longest first so prefix stripping is unambiguous.
_API_PREFIXES = ("/api/v1", "/api")

# Suffixes (relative to an API prefix) reachable without credentials even when
# AUTH_ENABLED is on: the metadata/health/docs endpoints and the endpoints used
# to *obtain* credentials in the first place.
_AUTH_EXEMPT_SUFFIXES = frozenset(
    {
        "/health",
        "/version",
        "/openapi.json",
        "/docs",
        "/auth/register",
        "/auth/login",
        "/auth/refresh",
    }
)


def _is_auth_exempt(path: str) -> bool:
    """Whether ``path`` is a credential-free endpoint under any API prefix."""
    for prefix in _API_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            if path[len(prefix):] in _AUTH_EXEMPT_SUFFIXES:
                return True
    return False


def _verify_security_posture(app: Flask) -> None:
    """Fail fast on an unsafe security posture at boot.

    In **production** (``AGENTSCOPE_ENV=production``) the app refuses to start
    unless authentication is enabled *and* strong, non-default secrets are set —
    so a fully open, forgeable-token deployment can never ship by accident. In
    **development** the historical zero-config behavior is preserved: auth is
    optional, but if it is turned on the same strong-secret requirement applies
    (an on-but-forgeable configuration is never allowed).
    """
    is_production = app.config.get("IS_PRODUCTION")
    auth_enabled = app.config.get("AUTH_ENABLED")

    if is_production and not auth_enabled:
        raise RuntimeError(
            "AGENTSCOPE_ENV=production requires AUTH_ENABLED=true: refusing to "
            "start with unauthenticated data routes. Enable auth (and set strong "
            "SECRET_KEY / JWT_SECRET), or run with AGENTSCOPE_ENV=development."
        )

    # Secrets must be strong whenever auth is in force: always in production,
    # and in development only when AUTH_ENABLED was explicitly turned on.
    if is_production or auth_enabled:
        weak = [
            name
            for name in ("SECRET_KEY", "JWT_SECRET")
            if app.config.get(name) in _DEFAULT_SECRETS
        ]
        if weak:
            reason = "production" if is_production else "AUTH_ENABLED=true"
            raise RuntimeError(
                f"{reason} requires strong, non-default secrets; set a random "
                f"value for: {', '.join(weak)}."
            )


def _register_auth_enforcement(app: Flask) -> None:
    """Require a valid principal on data routes when ``AUTH_ENABLED`` is set.

    Off by default so existing deployments stay backward compatible. When on,
    every ``/api`` route needs a valid JWT or API key except the health probe
    and the credential-issuing auth endpoints. Per-route decorators still own
    authorization (roles / org isolation); this hook only enforces that a
    request is *authenticated at all*, which is what ``AUTH_ENABLED`` promises.
    """
    from .auth import AuthError, resolve_identity, set_identity

    @app.before_request
    def _enforce_auth():  # pragma: no cover - exercised via app config in tests
        if not app.config.get("AUTH_ENABLED"):
            return None
        if request.method == "OPTIONS":
            return None  # let CORS preflight through
        path = request.path
        if not path.startswith("/api/") or _is_auth_exempt(path):
            return None
        identity = resolve_identity()  # raises AuthError on invalid credentials
        if identity is None:
            raise AuthError()
        set_identity(identity)
        return None


def _register_websocket(app: Flask) -> None:
    """Register the v0.6 WebSocket endpoint (flask-sock), if available.

    SSE has no extra dependency, so the app still boots and streams over
    ``/api/stream`` even if flask-sock is not installed.
    """
    try:
        from flask_sock import Sock

        from .routes.stream import register_websocket
    except ImportError:  # pragma: no cover - optional dependency
        logging.getLogger("agentscope").warning(
            "flask-sock not installed; WebSocket streaming disabled (SSE still available)"
        )
        return
    register_websocket(Sock(app))


def create_app(config_class: type[Config] = Config) -> Flask:
    """Create and configure a Flask application instance."""
    _configure_logging()

    app = Flask(__name__)
    app.config.from_object(config_class)
    _verify_security_posture(app)

    db.init_app(app)
    CORS(app, resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}})

    # Import models so SQLAlchemy is aware of them before create_all.
    from .models import (  # noqa: F401
        trace,
        agent_trace,
        rag_trace,
        workflow_trace,
        evaluation_trace,
        auth,
    )

    # Blueprints
    from .routes.traces import traces_bp
    from .routes.agent_traces import agent_traces_bp
    from .routes.chat import chat_bp
    from .routes.rag import rag_bp
    from .routes.workflows import workflows_bp
    from .routes.evaluations import evaluations_bp
    from .routes.stream import stream_bp
    from .routes.plugins import plugins_bp
    from .routes.providers import providers_bp
    from .routes.exports import exports_bp
    from .routes.auth import auth_bp
    from .routes.organizations import orgs_bp
    from .routes.jobs import jobs_bp
    from .routes.meta import meta_bp
    from .middleware.logging import register_request_logging
    from .auth import register_auth_error_handlers

    # Every API blueprint is mounted twice: under the versioned prefix
    # ``/api/v1`` (the canonical, documented contract) and under the
    # unversioned ``/api`` alias, which always maps to the current version so
    # existing clients keep working. Registering the same blueprint under two
    # prefixes requires a distinct ``name`` for the second mount.
    api_blueprints = (
        meta_bp,
        traces_bp,
        agent_traces_bp,
        chat_bp,
        rag_bp,
        workflows_bp,
        evaluations_bp,
        stream_bp,
        plugins_bp,
        providers_bp,
        exports_bp,
        auth_bp,
        orgs_bp,
        jobs_bp,
    )
    for bp in api_blueprints:
        app.register_blueprint(bp, url_prefix="/api")
        app.register_blueprint(bp, url_prefix="/api/v1", name=f"{bp.name}_v1")
    _register_websocket(app)
    register_request_logging(app)
    _register_auth_enforcement(app)
    register_error_handlers(app)
    register_auth_error_handlers(app)

    @app.after_request
    def _tag_api_version(response):
        """Advertise the served API contract version on every /api response."""
        if request.path.startswith("/api/"):
            response.headers.setdefault("X-API-Version", API_VERSION)
        return response

    _enable_sqlite_foreign_keys(app)
    # When migrations own the schema (USE_MIGRATIONS=true), the app must not
    # silently create tables — schema changes go through ``alembic upgrade head``
    # so production databases evolve safely instead of drifting.
    if not app.config.get("USE_MIGRATIONS"):
        with app.app_context():
            db.create_all()

    from .auth import configure_rate_limiter
    configure_rate_limiter(app)

    from .jobs import job_manager
    job_manager.init_app(app)

    from .plugins import init_plugins
    init_plugins(app)

    _configure_stream_broker(app)
    _register_lifecycle_shutdown(app)

    return app

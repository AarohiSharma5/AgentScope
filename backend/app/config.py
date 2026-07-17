"""Application configuration loaded from environment variables."""
import os

from dotenv import load_dotenv

# Load .env before any config values are read at class-definition time.
load_dotenv()

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    """Base configuration shared across environments."""

    # Deployment environment. "production"/"prod" turns on hard security guards
    # at boot (see the app factory): authentication must be enabled and secrets
    # must be non-default, so an open/forgeable deployment can never ship by
    # accident. Anything else (default "development") preserves the zero-config,
    # auth-optional experience. ``FLASK_ENV`` is honored as a fallback.
    ENVIRONMENT = (
        os.getenv("AGENTSCOPE_ENV") or os.getenv("FLASK_ENV") or "development"
    ).strip().lower()
    IS_PRODUCTION = ENVIRONMENT in {"production", "prod"}

    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")

    # Prefer PostgreSQL via DATABASE_URL; fall back to SQLite for zero-config dev.
    DATABASE_URL = os.getenv("DATABASE_URL")
    if DATABASE_URL:
        # SQLAlchemy expects the postgresql:// scheme (not postgres://).
        if DATABASE_URL.startswith("postgres://"):
            DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        SQLALCHEMY_DATABASE_URI = DATABASE_URL
    else:
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(
            basedir, "..", "agentscope.db"
        )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # When true, the schema is owned by Alembic migrations: the app will NOT
    # auto-create tables at boot, and you must run ``alembic upgrade head`` to
    # provision/evolve the database. Default false preserves the zero-config
    # ``create_all()`` behavior for SQLite/dev and existing deployments.
    USE_MIGRATIONS = os.getenv("USE_MIGRATIONS", "false").lower() == "true"

    # -- Connection pooling & query performance -----------------------------
    # A healthy connection pool is essential under concurrent load. These are
    # only meaningful for a real server backend (PostgreSQL); SQLite uses its
    # own pool implementation and ignores size-related options, so we apply the
    # full set only for non-SQLite URIs.
    _IS_SQLITE = SQLALCHEMY_DATABASE_URI.startswith("sqlite")
    if _IS_SQLITE:
        # `pool_pre_ping` still guards against stale connections cheaply.
        SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    else:
        SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_pre_ping": True,  # detect dropped connections before using them
            "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "1800")),  # recycle every 30m
            "pool_size": int(os.getenv("DB_POOL_SIZE", "10")),
            "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "20")),
            "pool_timeout": int(os.getenv("DB_POOL_TIMEOUT", "30")),
            "pool_use_lifo": True,  # reuse hot connections, let idle ones expire
        }

    # Short-lived in-process cache TTL (seconds) for expensive read-only
    # aggregations such as dashboard metrics. Set to 0 to disable caching.
    METRICS_CACHE_TTL = float(os.getenv("METRICS_CACHE_TTL", "5"))

    # Cap COUNT(*) on very large tables to keep list endpoints fast. A list
    # response reports up to this many rows as its total (with a flag), avoiding
    # a full-table count on millions of rows. Set to 0 to always count exactly.
    MAX_COUNT_LIMIT = int(os.getenv("MAX_COUNT_LIMIT", "0"))

    # Bounded worker pool for long-running background jobs (replay, evaluation,
    # comparison, export) so they never tie up request-handling threads.
    BACKGROUND_WORKERS = int(os.getenv("BACKGROUND_WORKERS", "4"))

    # Max branches of a workflow "parallel" node that run at once, per fan-out.
    # Extra branches queue and start as slots free up, so a wide parallel node
    # never spawns a thread-and-DB-connection per branch. Each concurrent branch
    # re-enters the app context and a handler that touches the ORM may hold one
    # pooled connection, so keep this comfortably below DB_POOL_SIZE +
    # DB_MAX_OVERFLOW; the real connection budget is this value multiplied by the
    # number of workflows running concurrently.
    WORKFLOW_MAX_PARALLELISM = int(os.getenv("WORKFLOW_MAX_PARALLELISM", "8"))

    # Maximum size (bytes) of an uploaded import bundle. Import reconstructs
    # arbitrary DB rows from the body, so cap it to bound memory/DoS. Default
    # 25 MiB; set 0 to disable the check.
    MAX_IMPORT_BYTES = int(os.getenv("MAX_IMPORT_BYTES", str(25 * 1024 * 1024)))

    CORS_ORIGINS = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
        if origin.strip()
    ]

    # -- Real-time streaming (v0.6) -----------------------------------------
    # Heartbeat cadence (seconds) for SSE/WebSocket connections.
    STREAM_HEARTBEAT_INTERVAL = float(os.getenv("STREAM_HEARTBEAT_INTERVAL", "15"))

    # -- Plugin system (v0.6) -----------------------------------------------
    # Discover, install and enable plugins at startup. Set False to disable.
    PLUGINS_AUTOLOAD = os.getenv("PLUGINS_AUTOLOAD", "true").lower() != "false"
    # Python packages scanned for self-registering plugins.
    PLUGINS_PACKAGES = [
        pkg.strip()
        for pkg in os.getenv("PLUGINS_PACKAGES", "app.plugins.builtins").split(",")
        if pkg.strip()
    ]
    # Optional filesystem directories of drop-in ``*.py`` plugins.
    PLUGINS_DIRECTORIES = [
        d.strip() for d in os.getenv("PLUGINS_DIRECTORIES", "").split(",") if d.strip()
    ]
    # Optional additional dotted module paths to import for discovery.
    PLUGINS_MODULES = [
        m.strip() for m in os.getenv("PLUGINS_MODULES", "").split(",") if m.strip()
    ]
    # Entry-point group used by pip-installed third-party plugins.
    PLUGINS_ENTRYPOINT_GROUP = os.getenv("PLUGINS_ENTRYPOINT_GROUP", "agentscope.plugins")

    # -- Authentication & multi-tenancy (v1.0) ------------------------------
    # Global enforcement on the existing data routes is OFF by default so the
    # platform stays 100% backward compatible; the auth/tenancy endpoints and
    # decorators are always available for opt-in protection.
    AUTH_ENABLED = os.getenv("AUTH_ENABLED", "false").lower() == "true"

    # JWT signing. Defaults to SECRET_KEY so a single secret suffices in dev.
    JWT_SECRET = os.getenv("JWT_SECRET") or os.getenv("SECRET_KEY", "dev-secret-key")
    JWT_ISSUER = os.getenv("JWT_ISSUER", "agentscope")
    JWT_ACCESS_TTL = int(os.getenv("JWT_ACCESS_TTL", "900"))  # 15 minutes
    JWT_REFRESH_TTL = int(os.getenv("JWT_REFRESH_TTL", "2592000"))  # 30 days

    # API keys are minted with this human-readable prefix (e.g. ``as_...``).
    API_KEY_PREFIX = os.getenv("API_KEY_PREFIX", "as")

    # Server-side pepper (secret salt) for API-key hashing. Keys are hashed with
    # HMAC-SHA256 keyed by this value rather than a bare SHA-256, so a stolen
    # ``key_hash`` column cannot be brute-forced/rainbow-tabled without also
    # stealing the pepper (which lives in config/secrets, not the DB). Defaults
    # to JWT_SECRET so a single strong secret peppers everything in dev; set a
    # dedicated value in production if you rotate them independently.
    API_KEY_PEPPER = os.getenv("API_KEY_PEPPER") or JWT_SECRET

    # Password hashing. An explicit, tunable work factor (rather than relying on
    # the library default) so cost can be raised over time. Werkzeug understands
    # ``pbkdf2:sha256:<iterations>``; if ``argon2-cffi`` is installed you may set
    # ``argon2`` for Argon2id. 600k PBKDF2 iterations follows OWASP guidance.
    PASSWORD_HASH_METHOD = os.getenv("PASSWORD_HASH_METHOD", "pbkdf2:sha256:600000")
    PASSWORD_MIN_LENGTH = int(os.getenv("PASSWORD_MIN_LENGTH", "8"))

    # Debounce window (seconds) for persisting ApiKey.last_used_at. Writing it on
    # every authenticated request causes write amplification / row-lock contention
    # on a hot key under ingest-heavy traffic; instead we persist at most once per
    # window per key. Set 0 to write on every request (exact, but contended).
    API_KEY_LAST_USED_DEBOUNCE_SECONDS = int(
        os.getenv("API_KEY_LAST_USED_DEBOUNCE_SECONDS", "60")
    )

    # Rate limiting. In-process (per worker) by default; set
    # ``RATE_LIMIT_STORAGE_URL`` to a Redis URL to share windows across workers
    # so the configured limits hold cluster-wide instead of being multiplied by
    # the worker count.
    RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() != "false"
    RATE_LIMIT_DEFAULT = os.getenv("RATE_LIMIT_DEFAULT", "120/minute")
    RATE_LIMIT_STORAGE_URL = os.getenv("RATE_LIMIT_STORAGE_URL") or None

    # Per-surface limits so ingest/chat/import are protected too (not just auth).
    # Ingest is high-throughput, so its default is generous; tighten per your
    # traffic. Keyed per authenticated principal (or client IP when auth is off).
    RATE_LIMIT_INGEST = os.getenv("RATE_LIMIT_INGEST", "1000/minute")
    RATE_LIMIT_CHAT = os.getenv("RATE_LIMIT_CHAT", "240/minute")
    RATE_LIMIT_IMPORT = os.getenv("RATE_LIMIT_IMPORT", "30/minute")

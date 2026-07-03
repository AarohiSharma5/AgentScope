"""Application configuration loaded from environment variables."""
import os

from dotenv import load_dotenv

# Load .env before any config values are read at class-definition time.
load_dotenv()

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    """Base configuration shared across environments."""

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

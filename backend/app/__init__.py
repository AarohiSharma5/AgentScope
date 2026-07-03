"""Application factory for the AgentScope backend."""
import logging
import sqlite3

from dotenv import load_dotenv
from flask import Flask, jsonify
from flask_cors import CORS
from sqlalchemy import event

from .config import Config
from .errors import register_error_handlers
from .extensions import db

load_dotenv()


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
    from .middleware.logging import register_request_logging
    from .auth import register_auth_error_handlers

    app.register_blueprint(traces_bp, url_prefix="/api")
    app.register_blueprint(agent_traces_bp, url_prefix="/api")
    app.register_blueprint(chat_bp, url_prefix="/api")
    app.register_blueprint(rag_bp, url_prefix="/api")
    app.register_blueprint(workflows_bp, url_prefix="/api")
    app.register_blueprint(evaluations_bp, url_prefix="/api")
    app.register_blueprint(stream_bp, url_prefix="/api")
    app.register_blueprint(plugins_bp, url_prefix="/api")
    app.register_blueprint(providers_bp, url_prefix="/api")
    app.register_blueprint(exports_bp, url_prefix="/api")
    app.register_blueprint(auth_bp, url_prefix="/api")
    app.register_blueprint(orgs_bp, url_prefix="/api")
    app.register_blueprint(jobs_bp, url_prefix="/api")
    _register_websocket(app)
    register_request_logging(app)
    register_error_handlers(app)
    register_auth_error_handlers(app)

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok", "service": "agentscope"})

    _enable_sqlite_foreign_keys(app)
    with app.app_context():
        db.create_all()

    from .jobs import job_manager
    job_manager.init_app(app)

    from .plugins import init_plugins
    init_plugins(app)

    return app

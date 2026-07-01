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


def create_app(config_class: type[Config] = Config) -> Flask:
    """Create and configure a Flask application instance."""
    _configure_logging()

    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    CORS(app, resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}})

    # Import models so SQLAlchemy is aware of them before create_all.
    from .models import trace, agent_trace  # noqa: F401

    # Blueprints
    from .routes.traces import traces_bp
    from .routes.agent_traces import agent_traces_bp
    from .routes.chat import chat_bp
    from .middleware.logging import register_request_logging

    app.register_blueprint(traces_bp, url_prefix="/api")
    app.register_blueprint(agent_traces_bp, url_prefix="/api")
    app.register_blueprint(chat_bp, url_prefix="/api")
    register_request_logging(app)
    register_error_handlers(app)

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok", "service": "agentscope"})

    _enable_sqlite_foreign_keys(app)
    with app.app_context():
        db.create_all()

    return app

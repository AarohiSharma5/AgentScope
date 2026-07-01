"""Application factory for the AgentScope backend."""
from flask import Flask, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

from .config import Config
from .extensions import db

load_dotenv()


def create_app(config_class: type[Config] = Config) -> Flask:
    """Create and configure a Flask application instance."""
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    CORS(app, resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}})

    # Register models so SQLAlchemy is aware of them before create_all.
    from .models import trace  # noqa: F401

    # Blueprints
    from .routes.traces import traces_bp
    from .routes.agent_traces import agent_traces_bp
    from .middleware.logging import register_request_logging

    app.register_blueprint(traces_bp, url_prefix="/api")
    app.register_blueprint(agent_traces_bp, url_prefix="/api")
    register_request_logging(app)

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok", "service": "agentscope"})

    with app.app_context():
        db.create_all()

    return app

"""Database models package.

Importing the model modules here ensures every model is registered with
SQLAlchemy's metadata (so ``db.create_all()`` sees them), regardless of which
module is imported first. This is additive only and does not alter existing
models or behavior.
"""
from . import trace  # noqa: F401  (existing RequestTrace / Trace model)
from . import agent_trace  # noqa: F401  (v0.2 agent execution tracing)

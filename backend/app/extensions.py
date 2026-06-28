"""Shared Flask extensions, instantiated here to avoid circular imports."""
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

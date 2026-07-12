"""Rejestracja blueprintów Flask (Faza C — modularne trasy)."""
from __future__ import annotations

from flask import Flask

from routes.files import bp as files_bp
from routes.license import bp as license_bp
from routes.meta import bp as meta_bp
from routes.rb_beta import bp as rb_beta_bp
from routes.session import bp as session_bp


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(meta_bp)
    app.register_blueprint(session_bp)
    app.register_blueprint(license_bp)
    app.register_blueprint(files_bp)
    app.register_blueprint(rb_beta_bp)

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

from flask import Flask, abort, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

from backend.extensions import jwt
from backend.routes.auth import auth_bp
from backend.routes.cart import cart_bp
from backend.routes.orders import orders_bp
from backend.routes.payments import payments_bp
from backend.routes.products import products_bp
from backend.telegram_admin_bot import start_background_bot


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _instance_dir() -> Path:
    return Path(__file__).resolve().parent / "instance"


def create_app() -> Flask:
    load_dotenv()

    project_root = _project_root()
    instance_dir = _instance_dir()
    instance_dir.mkdir(parents=True, exist_ok=True)

    app = Flask(__name__)
    default_secret = "dev-secret-key-change-me-please-32-bytes-minimum"
    access_expires_days = int(os.environ.get("JWT_ACCESS_TOKEN_EXPIRES_DAYS", "7"))
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", default_secret),
        JWT_SECRET_KEY=os.environ.get("JWT_SECRET_KEY", os.environ.get("SECRET_KEY", default_secret)),
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(days=access_expires_days),
        JSON_SORT_KEYS=False,
    )

    CORS(app, resources={r"/api/*": {"origins": "*"}})

    jwt.init_app(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(cart_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(products_bp)

    @app.get("/api/health")
    def _health():
        return {"ok": True, "service": "kok-emall-backend"}

    @app.get("/")
    def _index():
        return send_from_directory(project_root, "index.html")

    @app.get("/<path:filename>")
    def _static_files(filename: str):
        if filename.startswith("api/"):
            abort(404)
        return send_from_directory(project_root, filename)

    debug_enabled = os.environ.get("FLASK_DEBUG", "1") == "1"
    if not debug_enabled or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_background_bot()

    return app

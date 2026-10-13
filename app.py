import os
import secrets
import sys

from flask import Flask, jsonify, render_template, request
from flask_limiter.errors import RateLimitExceeded
from flask_wtf.csrf import CSRFError

import auth
from extensions import csrf, db, limiter, login_manager, migrate
from models import User

from sherlock_service import (
    MAX_SELECTED_SITES,
    SearchManager,
    SiteCatalog,
    TooManySearches,
    ValidationError,
    normalize_sites,
    normalize_username,
)


def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("postgres://"):  # formato antigo usado por alguns provedores
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url or "sqlite:///detective.db"  # relativo à pasta instance/


def secret_key() -> str:
    key = os.environ.get("SECRET_KEY")
    if key:
        return key
    if os.environ.get("RENDER"):
        raise RuntimeError("Defina a variável de ambiente SECRET_KEY em produção.")
    print("[aviso] SECRET_KEY não definida: usando chave temporária (sessões caem ao reiniciar).", file=sys.stderr)
    return secrets.token_hex(32)


def create_app(manager: SearchManager | None = None, config: dict | None = None) -> Flask:
    # instance_path fixo: sem isso, `python app.py` rodado de outra pasta usaria outro banco
    app = Flask(__name__, instance_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "instance"))
    production = bool(os.environ.get("RENDER"))
    app.config.update(
        MAX_CONTENT_LENGTH=64 * 1024,
        SECRET_KEY=None,
        SQLALCHEMY_DATABASE_URI=database_url(),
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=production,
        REMEMBER_COOKIE_HTTPONLY=True,
        REMEMBER_COOKIE_SAMESITE="Lax",
        REMEMBER_COOKIE_SECURE=production,
        REMEMBER_COOKIE_DURATION=60 * 60 * 24 * 30,
        WTF_CSRF_TIME_LIMIT=None,  # o token vale enquanto durar a sessão
    )
    app.config.update(config or {})
    if not app.config["SECRET_KEY"]:
        app.config["SECRET_KEY"] = secret_key()
    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    limiter.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Entre na sua conta para continuar."
    login_manager.login_message_category = "info"
    # "strong" derrubaria a sessão sempre que o IP muda (o proxy do Render varia o IP visto pelo app)
    login_manager.session_protection = "basic"

    @login_manager.user_loader
    def load_user(user_id: str):
        return db.session.get(User, int(user_id)) if user_id.isdigit() else None

    app.register_blueprint(auth.bp)
    app.register_error_handler(RateLimitExceeded, auth.handle_rate_limit)

    if manager is None:
        manager = SearchManager(
            SiteCatalog(),
            max_workers=int(os.environ.get("SEARCH_WORKERS", 2)),
            site_timeout=int(os.environ.get("SITE_TIMEOUT", 15)),
        )
    app.extensions["search_manager"] = manager
    catalog = manager.catalog

    def client_id() -> str:
        # Atrás de proxy (Render), o IP real vem no primeiro X-Forwarded-For.
        fwd = request.headers.get("X-Forwarded-For", "")
        return (fwd.split(",")[0].strip() if fwd else request.remote_addr) or "?"

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            total_sites=len(catalog),
            popular_sites=catalog.popular(),
            all_sites=catalog.names(),
            max_sites=MAX_SELECTED_SITES,
        )

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "sites": len(catalog)}

    @app.post("/api/search")
    def start_search():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="Requisição inválida."), 400
        sites = payload.get("sites")
        if sites is not None and not (isinstance(sites, list) and all(isinstance(s, str) for s in sites)):
            return jsonify(error="Lista de sites inválida."), 400
        try:
            username = normalize_username(payload.get("username") if isinstance(payload.get("username"), str) else None)
            selected = normalize_sites(catalog, payload.get("mode"), sites)
            job = manager.start(username, selected, owner=client_id())
        except ValidationError as exc:
            return jsonify(error=str(exc)), 400
        except TooManySearches as exc:
            return jsonify(error=str(exc)), 429
        return jsonify(job.to_dict()), 202

    @app.get("/api/search/<job_id>")
    def search_status(job_id: str):
        job = manager.get(job_id)
        if job is None:
            return jsonify(error="Busca não encontrada ou expirada."), 404
        return jsonify(job.to_dict())

    @app.post("/api/search/<job_id>/verify")
    def verify_links(job_id: str):
        job = manager.get(job_id)
        if job is None:
            return jsonify(error="Busca não encontrada ou expirada."), 404
        payload = request.get_json(silent=True)
        seed = payload.get("seed") if isinstance(payload, dict) else None
        if not isinstance(seed, str) or not seed.strip():
            return jsonify(error="Informe o perfil de referência."), 400
        try:
            manager.start_verification(job, seed)
        except ValidationError as exc:
            return jsonify(error=str(exc)), 400
        except TooManySearches as exc:
            return jsonify(error=str(exc)), 409
        return jsonify(job.to_dict()), 202

    @app.errorhandler(CSRFError)
    def csrf_error(_):
        if request.path.startswith("/api/"):
            return jsonify(error="Sessão expirada. Recarregue a página."), 400
        return render_template("auth/csrf_error.html"), 400

    @app.errorhandler(404)
    def not_found(_):
        if request.path.startswith("/api/"):
            return jsonify(error="Recurso não encontrado."), 404
        return render_template("404.html"), 404

    @app.errorhandler(405)
    def method_not_allowed(_):
        return jsonify(error="Método não permitido."), 405

    @app.errorhandler(413)
    def too_large(_):
        return jsonify(error="Requisição muito grande."), 413

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: https://www.google.com https://*.gstatic.com; "
            "style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
            "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.path.startswith("/api/"):
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    return app


app = create_app()

if __name__ == "__main__":
    # Rode: python app.py  (o modo debug só liga com FLASK_DEBUG=1)
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", 5000)),
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )

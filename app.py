import os

from flask import Flask, jsonify, render_template, request

from sherlock_service import (
    MAX_SELECTED_SITES,
    SearchManager,
    SiteCatalog,
    TooManySearches,
    ValidationError,
    normalize_sites,
    normalize_username,
)


def create_app(manager: SearchManager | None = None) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024

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

    # ------------------------------------------------------------------ erros
    # Textos de cada erro tratado: (título da página, mensagem da página, mensagem da API).
    # Para tratar um novo código, basta acrescentar uma linha aqui e no laço abaixo.
    ERRORS = {
        404: ("Página não encontrada", "Procuramos por toda parte, mas essa página não existe ou foi movida.",
              "Recurso não encontrado."),
        405: ("Ação não permitida", "Esse endereço não aceita esse tipo de acesso.", "Método não permitido."),
        413: ("Requisição muito grande", "Os dados enviados passaram do limite permitido.", "Requisição muito grande."),
        500: ("Algo deu errado", "Tivemos um problema inesperado. Tente de novo em instantes.",
              "Erro interno. Tente novamente."),
    }

    def error_response(code: int):
        """Monta a resposta de erro no formato certo para quem pediu.

        A API (/api/...) é consumida pelo JavaScript, que espera JSON {"error": ...};
        as demais rotas são abertas no navegador e recebem a página templates/error.html.
        """
        title, message, api_message = ERRORS[code]
        if request.path.startswith("/api/"):
            return jsonify(error=api_message), code
        return render_template("error.html", code=code, title=title, message=message), code

    # 404 (rota inexistente), 405 (método errado) e 413 (corpo grande demais) usam a mesma
    # função. O "c=_code" fixa o código de cada lambda; sem ele, todas usariam o último (413).
    for _code in (404, 405, 413):
        app.register_error_handler(_code, lambda _e, c=_code: error_response(c))

    @app.errorhandler(500)
    def internal_error(err):
        # Qualquer exceção não tratada chega aqui. A exceção original (com traceback) vai
        # para o log do servidor; o usuário vê só a página amigável, sem detalhes internos.
        app.logger.error("Erro 500 em %s", request.path, exc_info=getattr(err, "original_exception", err))
        return error_response(500)

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

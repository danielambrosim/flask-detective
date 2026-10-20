"""Páginas de erro (HTML) e respostas de erro da API (JSON)."""
import pytest

from app import create_app


@pytest.fixture
def crash_client(manager):
    app = create_app(manager)
    app.config["PROPAGATE_EXCEPTIONS"] = False  # simula produção: erro vira página 500

    @app.get("/boom")
    def boom():
        raise RuntimeError("detalhe-interno-secreto")

    @app.get("/api/boom")
    def api_boom():
        raise RuntimeError("detalhe-interno-secreto")

    return app.test_client()


def test_404_pagina(client):
    r = client.get("/pagina/que/nao/existe")
    html = r.get_data(as_text=True)
    assert r.status_code == 404
    assert "Página não encontrada" in html and "Erro 404" in html
    assert 'class="site-header"' in html and 'class="site-footer"' in html  # mesmo layout do site
    assert 'action="/"' in html and 'name="u"' in html  # campo para buscar de novo
    assert 'name="robots" content="noindex"' in html


def test_404_na_api_continua_json(client):
    r = client.get("/api/nada")
    assert r.status_code == 404 and r.get_json() == {"error": "Recurso não encontrado."}


def test_405_pagina_e_api(client):
    r = client.post("/")
    assert r.status_code == 405 and "Ação não permitida" in r.get_data(as_text=True)
    r = client.get("/api/search")
    assert r.status_code == 405 and r.get_json()["error"] == "Método não permitido."


def test_413_na_api(client):
    r = client.post("/api/search", data="x" * 70_000, content_type="application/json")
    assert r.status_code == 413 and "error" in r.get_json()


def test_500_pagina_sem_vazar_detalhes(crash_client):
    r = crash_client.get("/boom")
    html = r.get_data(as_text=True)
    assert r.status_code == 500
    assert "Algo deu errado" in html and "Tentar de novo" in html
    assert "detalhe-interno-secreto" not in html and "Traceback" not in html


def test_500_na_api_e_json(crash_client):
    r = crash_client.get("/api/boom")
    assert r.status_code == 500
    assert r.get_json() == {"error": "Erro interno. Tente novamente."}


def test_500_e_registrado_no_log(crash_client, caplog):
    crash_client.get("/boom")
    assert any("Erro 500 em /boom" in rec.getMessage() and rec.exc_info for rec in caplog.records)


def test_pagina_de_erro_tem_cabecalhos_de_seguranca(client):
    r = client.get("/nao-existe")
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]


def test_pagina_de_erro_sem_script_inline(client):
    html = client.get("/nao-existe").get_data(as_text=True)
    assert "<script" not in html

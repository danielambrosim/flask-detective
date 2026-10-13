"""Cabeçalhos e configuração de segurança."""
import sys

import app as app_module


def test_cabecalhos_de_seguranca(client):
    r = client.get("/")
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"


def test_api_nao_e_cacheada(client):
    r = client.post("/api/search", json={"username": ""})
    assert r.headers["Cache-Control"] == "no-store"


def test_template_nao_tem_script_inline(client):
    # Necessário para a CSP "script-src 'self'" funcionar
    html = client.get("/").get_data(as_text=True)
    assert "<script>" not in html and "onclick=" not in html


def test_resposta_nao_expoe_caminhos_do_servidor(client):
    # A versão original mostrava o comando completo (com caminho do Python) no "diagnóstico"
    assert sys.executable not in client.get("/").get_data(as_text=True)


def test_debug_desligado_por_padrao():
    assert app_module.app.debug is False

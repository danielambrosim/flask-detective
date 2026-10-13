"""Rotas HTTP."""
from tests.conftest import wait_job


def test_pagina_inicial(client, catalog):
    r = client.get("/")
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert f"{len(catalog)} sites" in html
    assert 'name="sites" value="GitHub"' in html
    assert 'data-site="DeviantART"' in html


def test_healthz(client):
    assert client.get("/healthz").get_json()["status"] == "ok"


def test_fluxo_completo(client, runner):
    r = client.post("/api/search", json={"username": "@torvalds", "mode": "custom", "sites": ["github", "reddit"]})
    assert r.status_code == 202
    job = r.get_json()
    assert job["username"] == "torvalds"
    data = wait_job(client, job["id"])
    assert data["status"] == "done"
    assert {f["site"] for f in data["found"]} == {"GitHub", "Reddit"}
    assert runner.calls[0]["sites"] == ["GitHub", "Reddit"]


def test_usuario_invalido_retorna_400(client, runner):
    r = client.post("/api/search", json={"username": "--version"})
    assert r.status_code == 400
    assert "inválido" in r.get_json()["error"]
    assert runner.calls == []


def test_custom_sem_sites_retorna_400(client):
    r = client.post("/api/search", json={"username": "abc", "mode": "custom", "sites": []})
    assert r.status_code == 400


def test_payload_malformado(client):
    assert client.post("/api/search", data="nao-json", content_type="application/json").status_code == 400
    assert client.post("/api/search", json=["lista"]).status_code == 400
    assert client.post("/api/search", json={"username": 123}).status_code == 400
    assert client.post("/api/search", json={"username": "a", "mode": "custom", "sites": "GitHub"}).status_code == 400
    assert client.post("/api/search", json={"username": "a", "mode": "custom", "sites": [1, 2]}).status_code == 400


def test_payload_muito_grande(client):
    r = client.post("/api/search", data="x" * 70_000, content_type="application/json")
    assert r.status_code == 413


def test_job_inexistente(client):
    r = client.get("/api/search/naoexiste")
    assert r.status_code == 404 and "error" in r.get_json()


def test_rate_limit_por_cliente(client, runner):
    runner.release.clear()
    h = {"X-Forwarded-For": "9.9.9.9"}
    assert client.post("/api/search", json={"username": "a"}, headers=h).status_code == 202
    r = client.post("/api/search", json={"username": "b"}, headers=h)
    assert r.status_code == 429
    runner.release.set()


def test_metodo_nao_permitido(client):
    assert client.get("/api/search").status_code == 405


def test_404_html(client):
    r = client.get("/nao-existe")
    assert r.status_code == 404 and "Voltar para a busca" in r.get_data(as_text=True)

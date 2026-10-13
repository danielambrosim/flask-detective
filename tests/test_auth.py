"""Login, cadastro e logout."""
import re
from urllib.parse import quote

import pytest

from extensions import db
from models import User
from tests.conftest import make_app

GOOD = {"name": "Maria Silva", "email": "maria@exemplo.com", "password": "senhaForte123", "confirm": "senhaForte123"}


def signup(client, **over):
    return client.post("/cadastrar", data={**GOOD, **over})


def login(client, email=GOOD["email"], password=GOOD["password"], **extra):
    return client.post("/entrar", data={"email": email, "password": password, **extra})


def users(app):
    with app.app_context():
        return db.session.execute(db.select(User)).scalars().all()


@pytest.fixture
def registered(client):
    signup(client)
    client.post("/sair")
    client.get("/")  # consome o aviso "Você saiu da sua conta"
    return client


# ----------------------------------------------------------------- páginas
@pytest.mark.parametrize("path, text", [("/entrar", "Entrar"), ("/cadastrar", "Criar conta")])
def test_paginas_abrem(client, path, text):
    r = client.get(path)
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert f"<h1>{text}</h1>" in html
    assert 'name="email"' in html and 'type="password"' in html


def test_header_mostra_entrar_para_visitante(client):
    html = client.get("/").get_data(as_text=True)
    assert 'href="/entrar"' in html and 'href="/cadastrar"' in html


# ---------------------------------------------------------------- cadastro
def test_cadastro_cria_usuario_e_ja_loga(client, app):
    r = signup(client)
    assert r.status_code == 302 and r.headers["Location"] == "/"
    [user] = users(app)
    assert user.email == "maria@exemplo.com" and user.name == "Maria Silva"
    html = client.get("/").get_data(as_text=True)
    assert "Maria" in html and 'action="/sair"' in html


def test_senha_guardada_com_argon2(client, app):
    signup(client)
    [user] = users(app)
    assert user.password_hash.startswith("$argon2id$")
    assert GOOD["password"] not in user.password_hash


def test_email_e_normalizado(client, app):
    signup(client, email="  Maria@Exemplo.COM ")
    assert users(app)[0].email == "maria@exemplo.com"


@pytest.mark.parametrize("over, msg", [
    ({"name": ""}, "Informe seu nome"),
    ({"name": "M"}, "entre 2 e 60"),
    ({"email": "nao-e-email"}, "E-mail inválido"),
    ({"password": "abc12", "confirm": "abc12"}, "entre 8 e 128"),
    ({"password": "somenteletras", "confirm": "somenteletras"}, "letras e números"),
    ({"password": "12345678", "confirm": "12345678"}, "letras e números"),
    ({"confirm": "outraSenha123"}, "não conferem"),
    ({"email": "a1b2c3d4@x.com", "password": "a1b2c3d4@x.com", "confirm": "a1b2c3d4@x.com"}, "igual ao e-mail"),
    ({"password": "a1" * 65, "confirm": "a1" * 65}, "entre 8 e 128"),
])
def test_cadastro_invalido(client, app, over, msg):
    r = signup(client, **over)
    assert r.status_code == 400
    assert msg in r.get_data(as_text=True)
    assert users(app) == []


def test_email_duplicado(registered, app):
    r = signup(registered, email="MARIA@exemplo.com", name="Outra Pessoa")
    assert r.status_code == 400
    assert "Já existe uma conta" in r.get_data(as_text=True)
    assert len(users(app)) == 1


def test_nome_com_html_e_escapado(client):
    signup(client, name="<script>alert(1)</script>")
    html = client.get("/").get_data(as_text=True)
    assert "<script>alert(1)" not in html
    assert "&lt;script&gt;" in html


# ------------------------------------------------------------------- login
def test_login_correto(registered):
    r = login(registered)
    assert r.status_code == 302
    assert 'action="/sair"' in registered.get("/").get_data(as_text=True)


def test_login_ignora_maiusculas_no_email(registered):
    assert login(registered, email="MARIA@EXEMPLO.COM").status_code == 302


def test_senha_errada_e_email_inexistente_tem_mesma_resposta(registered):
    wrong = login(registered, password="senhaErrada999")
    unknown = login(registered, email="ninguem@exemplo.com")
    assert wrong.status_code == unknown.status_code == 400
    assert "E-mail ou senha incorretos" in wrong.get_data(as_text=True)
    # ignora só os valores que mudam a cada requisição (token CSRF, e-mail digitado)
    strip = lambda r: re.sub(r'(value|content)="[^"]*"', "", r.get_data(as_text=True))  # noqa: E731
    assert strip(wrong) == strip(unknown)  # não revela quais e-mails existem


def test_login_campos_vazios(client):
    r = client.post("/entrar", data={})
    assert r.status_code == 400 and "Informe seu e-mail" in r.get_data(as_text=True)


def test_manter_conectado_cria_cookie_de_lembrar(registered):
    r = login(registered, remember="y")
    assert any(c.startswith("remember_token=") for c in r.headers.getlist("Set-Cookie"))


def test_sem_manter_conectado_nao_cria_cookie(registered):
    r = login(registered)
    assert not any(c.startswith("remember_token=") for c in r.headers.getlist("Set-Cookie"))


def test_logado_nao_ve_tela_de_login(client):
    signup(client)
    assert client.get("/entrar").status_code == 302
    assert client.get("/cadastrar").status_code == 302


def test_login_limpa_sessao_anterior(registered):
    with registered.session_transaction() as s:
        s["dado_antigo"] = "x"
    login(registered)
    with registered.session_transaction() as s:
        assert "dado_antigo" not in s


# ------------------------------------------------------------- redirecionamento
@pytest.mark.parametrize("next_url, expected", [
    ("/#busca", "/#busca"),
    ("https://golpe.com", "/"),
    ("//golpe.com", "/"),
    ("/\\golpe.com", "/"),
    ("javascript:alert(1)", "/"),
    ("", "/"),
])
def test_next_so_aceita_caminho_interno(registered, next_url, expected):
    r = registered.post("/entrar?next=" + quote(next_url, safe=""), data={"email": GOOD["email"], "password": GOOD["password"]})
    assert r.headers["Location"] == expected


# ------------------------------------------------------------------ logout
def test_logout(registered):
    login(registered)
    r = registered.post("/sair")
    assert r.status_code == 302
    assert 'href="/entrar"' in registered.get("/").get_data(as_text=True)


def test_logout_exige_post(registered):
    login(registered)
    assert registered.get("/sair").status_code == 405


def test_logout_sem_estar_logado_redireciona_para_login(client):
    r = client.post("/sair")
    assert r.status_code == 302 and r.headers["Location"].startswith("/entrar")


# --------------------------------------------------------------- segurança
def test_cookie_de_sessao_seguro(client):
    r = signup(client)
    cookie = next(c for c in r.headers.getlist("Set-Cookie") if c.startswith("session="))
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie


def test_cookie_secure_em_producao(manager, monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    app = make_app(manager)
    assert app.config["SESSION_COOKIE_SECURE"] and app.config["REMEMBER_COOKIE_SECURE"]


def test_producao_exige_secret_key(manager, monkeypatch):
    from app import create_app
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app(manager, config={"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})


@pytest.fixture
def csrf_client(manager):
    return make_app(manager, WTF_CSRF_ENABLED=True).test_client()


def csrf_from(html):
    return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)


def test_csrf_bloqueia_formulario_sem_token(csrf_client):
    r = csrf_client.post("/cadastrar", data=GOOD)
    assert r.status_code == 400 and "Sessão expirada" in r.get_data(as_text=True)


def test_csrf_aceita_formulario_com_token(csrf_client):
    token = csrf_from(csrf_client.get("/cadastrar").get_data(as_text=True))
    assert csrf_client.post("/cadastrar", data={**GOOD, "csrf_token": token}).status_code == 302


def test_csrf_na_api_de_busca(csrf_client):
    payload = {"username": "torvalds", "mode": "custom", "sites": ["GitHub"]}
    r = csrf_client.post("/api/search", json=payload)
    assert r.status_code == 400 and "Sessão expirada" in r.get_json()["error"]
    token = csrf_from(csrf_client.get("/").get_data(as_text=True))
    assert csrf_client.post("/api/search", json=payload, headers={"X-CSRFToken": token}).status_code == 202


def test_limite_de_tentativas_de_login(manager):
    client = make_app(manager, RATELIMIT_ENABLED=True).test_client()
    codes = [login(client, password=f"errada{i}").status_code for i in range(11)]
    assert codes[:10] == [400] * 10
    assert codes[10] == 429
    assert "Muitas tentativas" in login(client).get_data(as_text=True)


# ------------------------------------------------------------------ modelo
def test_check_password(app):
    u = User(name="Ana", email="ana@x.com")
    u.set_password("abc12345")
    assert u.check_password("abc12345")
    assert not u.check_password("abc123456")
    assert not u.check_password("")
    u.password_hash = "lixo"
    assert not u.check_password("abc12345")


def test_cada_hash_e_unico(app):
    a, b = User(name="A", email="a@x.com"), User(name="B", email="b@x.com")
    a.set_password("mesmaSenha1")
    b.set_password("mesmaSenha1")
    assert a.password_hash != b.password_hash  # salt aleatório


# --------------------------------------------------------------- migration
def test_migration_sobe_e_desce(manager, tmp_path):
    import os

    from flask_migrate import downgrade, upgrade
    from sqlalchemy import inspect

    app = make_app(manager, SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'm.db'}")
    migrations = os.path.join(os.path.dirname(os.path.dirname(__file__)), "migrations")
    with app.app_context():
        db.drop_all()
        upgrade(directory=migrations)
        assert "users" in inspect(db.engine).get_table_names()
        downgrade(directory=migrations, revision="base")
        assert "users" not in inspect(db.engine).get_table_names()
        db.engine.dispose()


def test_banco_local_fica_na_pasta_do_projeto(manager, tmp_path, monkeypatch):
    # Regressão: rodar `python app.py` de outra pasta criava outro banco (vazio) nela
    import os
    monkeypatch.chdir(tmp_path)
    app = make_app(manager)
    project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert app.instance_path == os.path.join(project, "instance")
    assert not (tmp_path / "instance").exists()


def test_sessao_sobrevive_a_troca_de_ip(registered):
    # Regressão: com session_protection="strong", trocar IP/navegador deslogava o usuário
    # (atrás do proxy do Render o IP visto pelo app muda entre requisições)
    login(registered)
    r = registered.get("/", environ_base={"REMOTE_ADDR": "10.9.8.7", "HTTP_USER_AGENT": "Celular/1.0"})
    assert 'action="/sair"' in r.get_data(as_text=True)

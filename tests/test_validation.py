"""Validação de entrada: usuário e lista de sites."""
import pytest

from sherlock_service import MAX_SELECTED_SITES, ValidationError, normalize_sites, normalize_username


@pytest.mark.parametrize("raw, expected", [
    ("torvalds", "torvalds"),
    ("  @daniel.churros ", "daniel.churros"),
    ("@@user_1", "user_1"),
    ("a", "a"),
    ("x" * 50, "x" * 50),
    ("John-Doe", "John-Doe"),
])
def test_usernames_validos(raw, expected):
    assert normalize_username(raw) == expected


@pytest.mark.parametrize("raw", [
    "", "   ", "@", None,
    "--version",         # injeção de argumento no CLI (falha da versão original)
    "-h", "--nsfw",
    ".hidden",
    "x" * 51,
    "nome com espaco",
    "user;rm -rf /",
    "<script>",
    "user{?}",           # sintaxe de variações do Sherlock
    "usuário",           # acentos
    "../etc/passwd",
])
def test_usernames_invalidos(raw):
    with pytest.raises(ValidationError):
        normalize_username(raw)


def test_modo_all_retorna_none(catalog):
    assert normalize_sites(catalog, "all", ["GitHub"]) is None
    assert normalize_sites(catalog, None, None) is None


def test_sites_sao_normalizados_para_grafia_do_catalogo(catalog):
    # No catálogo é "DeviantART"; a versão original mandava "DeviantArt"
    assert normalize_sites(catalog, "custom", ["github", "deviantart", "GitHub"]) == ["GitHub", "DeviantART"]


def test_modo_custom_sem_sites_e_rejeitado(catalog):
    # Na versão original isso caía silenciosamente em "todos os sites"
    with pytest.raises(ValidationError, match="pelo menos um"):
        normalize_sites(catalog, "custom", [])


def test_site_inexistente_e_rejeitado(catalog):
    with pytest.raises(ValidationError, match="não suportado"):
        normalize_sites(catalog, "custom", ["GitHub", "SiteQueNaoExiste"])


def test_limite_de_sites(catalog):
    many = catalog.names()[: MAX_SELECTED_SITES + 1]
    with pytest.raises(ValidationError, match="no máximo"):
        normalize_sites(catalog, "custom", many)


def test_modo_invalido(catalog):
    with pytest.raises(ValidationError):
        normalize_sites(catalog, "hack", [])

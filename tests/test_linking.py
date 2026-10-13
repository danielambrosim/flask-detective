"""Vínculo entre perfis: os sites encontrados são mesmo da pessoa do perfil de referência?

Cenário (pessoa fictícia): o nome "maria.silva" foi pego no Instagram. O Sherlock
encontrou o mesmo nome em vários sites, mas só alguns são dela. Os outros são
homônimos: outra pessoa com o mesmo nome de usuário.
"""
import pytest

from linking import LinkVerifier, extract_links, link_points_to, normalize_host

USER = "maria.silva"

FOUND = [
    {"site": "Instagram", "url": "https://www.instagram.com/maria.silva"},
    {"site": "GitHub", "url": "https://www.github.com/maria.silva"},
    {"site": "Twitter", "url": "https://x.com/maria.silva"},
    {"site": "YouTube", "url": "https://www.youtube.com/@maria.silva"},
    {"site": "Reddit", "url": "https://www.reddit.com/user/maria.silva"},
    {"site": "Medium", "url": "https://medium.com/@maria.silva"},
    {"site": "Spotify", "url": "https://open.spotify.com/user/maria.silva"},
]

PAGES = {
    # Bio do Instagram (vem dentro de JSON, com barras escapadas)
    "https://www.instagram.com/maria.silva":
        '<script>{"biography":"dev","bio_links":[{"url":"https:\\/\\/github.com\\/maria.silva"},'
        '{"url":"https:\\/\\/twitter.com\\/maria.silva"}]}</script>',
    # GitHub: link de volta para o Instagram + canal do YouTube (rel="me")
    "https://www.github.com/maria.silva":
        '<a rel="nofollow me" href="https://www.youtube.com/@maria.silva">YouTube</a>'
        '<a href="https://github.com/maria.silva/projeto">repo</a>'
        '<a href="https://instagram.com/maria.silva/">insta</a>',
    # X e YouTube renderizam via JavaScript: nenhum link no HTML
    "https://x.com/maria.silva": "<html><body><div id=root></div></body></html>",
    "https://www.youtube.com/@maria.silva": "<html></html>",
    # Homônimo no Reddit: outra pessoa, que linka outras contas
    "https://www.reddit.com/user/maria.silva":
        '<a href="https://www.reddit.com/r/futebol">r/futebol</a>'
        '<a href="https://x.com/outra_maria">meu X</a>'
        '<a href="http://169.254.169.254/latest/meta-data">x</a>',
    # Homônimo no Medium: linka um Instagram parecido, mas não igual
    "https://medium.com/@maria.silva": '<a href="https://instagram.com/maria.silva2">insta</a>',
}


class FakeWeb:
    def __init__(self, pages=PAGES, api=None, fail=("https://open.spotify.com/user/maria.silva",)):
        self.pages = pages
        self.api = api or {}
        self.fail = set(fail)
        self.fetched = []

    def page(self, url):
        self.fetched.append(url)
        if url in self.fail:
            raise ConnectionError("site fora do ar")
        return self.pages.get(url, "")

    def json(self, url):
        self.fetched.append(url)
        return self.api.get(url)


@pytest.fixture
def web():
    return FakeWeb()


@pytest.fixture
def outcome(web):
    return LinkVerifier(fetch_page=web.page, fetch_json=web.json).verify(USER, "Instagram", FOUND)


def status(outcome, site):
    return outcome["sites"][site]["status"]


# ------------------------------------------------------------- cenário principal
def test_instagram_e_a_referencia(outcome):
    assert status(outcome, "Instagram") == "seed"


def test_perfis_linkados_pelo_instagram_sao_confirmados(outcome):
    assert status(outcome, "GitHub") == "confirmed"
    # a bio usa twitter.com; o Sherlock encontrou em x.com: é o mesmo serviço
    assert status(outcome, "Twitter") == "confirmed"
    assert "Instagram" in outcome["sites"]["Twitter"]["evidence"]


def test_perfil_ligado_a_um_confirmado_e_provavel(outcome):
    # O Instagram não cita o YouTube, mas o GitHub (já confirmado) cita
    assert status(outcome, "YouTube") == "probable"
    assert "GitHub" in outcome["sites"]["YouTube"]["evidence"]


def test_homonimos_nao_sao_vinculados(outcome):
    # Mesmo nome de usuário, mas nenhuma ligação com a maria.silva do Instagram
    assert status(outcome, "Reddit") == "unverified"
    # instagram.com/maria.silva2 não é instagram.com/maria.silva
    assert status(outcome, "Medium") == "unverified"


def test_site_fora_do_ar_nao_derruba_a_verificacao(outcome):
    assert status(outcome, "Spotify") == "unverified"


def test_todos_os_sites_recebem_um_status(outcome):
    assert set(outcome["sites"]) == {r["site"] for r in FOUND}
    assert sum(s["status"] in ("confirmed", "probable") for s in outcome["sites"].values()) == 3


def test_so_acessa_urls_de_perfil_geradas_pelo_sherlock(web, outcome):
    # Links achados nas páginas (ex.: 169.254.169.254) nunca são acessados (sem SSRF)
    allowed = {r["url"] for r in FOUND} | {
        f"https://api.github.com/users/{USER}", f"https://api.github.com/users/{USER}/social_accounts"}
    assert set(web.fetched) <= allowed
    assert not any("169.254" in u or "outra_maria" in u for u in web.fetched)


# ----------------------------------------------------------------- outros casos
def test_vinculo_declarado_so_do_outro_lado(web):
    # O Instagram não linka nada, mas o GitHub aponta para o Instagram
    pages = dict(PAGES)
    pages["https://www.instagram.com/maria.silva"] = "<html></html>"
    out = LinkVerifier(fetch_page=FakeWeb(pages).page, fetch_json=web.json).verify(USER, "Instagram", FOUND)
    assert status(out, "GitHub") == "confirmed"
    assert "aponta para o Instagram" in out["sites"]["GitHub"]["evidence"]
    assert status(out, "YouTube") == "probable"
    assert status(out, "Twitter") == "unverified"


def test_instagram_sem_login_nao_comprova_nada():
    # Caso real mais comum: sem login, o Instagram não mostra a bio
    empty = FakeWeb(pages={})
    out = LinkVerifier(fetch_page=empty.page, fetch_json=empty.json).verify(USER, "Instagram", FOUND)
    assert out["seed_links"] == 0
    assert all(s["status"] == "unverified" for site, s in out["sites"].items() if site != "Instagram")


def test_contas_declaradas_na_api_do_github():
    found = [
        {"site": "GitHub", "url": "https://www.github.com/maria.silva"},
        {"site": "Twitter", "url": "https://x.com/maria.silva"},
        {"site": "Bluesky", "url": "https://bsky.app/profile/maria.silva"},
    ]
    api = {
        "https://api.github.com/users/maria.silva/social_accounts": [
            {"provider": "bluesky", "url": "https://bsky.app/profile/maria.silva"}],
        "https://api.github.com/users/maria.silva": {"twitter_username": "maria.silva", "blog": ""},
    }
    web = FakeWeb(pages={}, api=api)
    out = LinkVerifier(fetch_page=web.page, fetch_json=web.json).verify(USER, "GitHub", found)
    assert status(out, "Twitter") == "confirmed"
    assert status(out, "Bluesky") == "confirmed"


def test_limite_de_paginas(web):
    out = LinkVerifier(fetch_page=web.page, fetch_json=web.json, max_pages=3).verify(USER, "Instagram", FOUND)
    assert out["checked"] == 3
    assert "limite" in out["sites"]["Medium"]["evidence"]


def test_referencia_precisa_estar_entre_os_encontrados(web):
    with pytest.raises(ValueError):
        LinkVerifier(fetch_page=web.page, fetch_json=web.json).verify(USER, "LinkedIn", FOUND)


# ------------------------------------------------------------------- unidades
@pytest.mark.parametrize("host, expected", [
    ("www.twitter.com", "x.com"), ("mobile.twitter.com", "x.com"), ("m.youtube.com", "youtube.com"),
    ("WWW.GitHub.com", "github.com"), ("instagr.am", "instagram.com"),
])
def test_normalize_host(host, expected):
    assert normalize_host(host) == expected


@pytest.mark.parametrize("link, profile, expected", [
    ("https://twitter.com/maria.silva", "https://x.com/maria.silva", True),
    ("https://x.com/Maria.Silva?s=20", "https://x.com/maria.silva", True),
    ("https://www.youtube.com/@maria.silva/videos", "https://youtube.com/@maria.silva", True),
    ("https://maria.silva.deviantart.com", "https://www.deviantart.com/maria.silva", True),
    ("https://x.com/maria.silva2", "https://x.com/maria.silva", False),
    ("https://x.com/outra", "https://x.com/maria.silva", False),
    ("https://evil.com/maria.silva", "https://x.com/maria.silva", False),
    ("https://notx.com/maria.silva", "https://x.com/maria.silva", False),
])
def test_link_points_to(link, profile, expected):
    assert link_points_to(link, profile, USER) is expected


def test_extract_links_de_varios_formatos():
    page = ('<a href="https://a.com/x">a</a> texto https://b.com/y. '
            '{"u":"https:\\/\\/c.com\\/z"} <link rel="me" href="https://d.com/w"> &quot;https://e.com/v&quot;')
    assert extract_links(page) == {"https://a.com/x", "https://b.com/y", "https://c.com/z",
                                   "https://d.com/w", "https://e.com/v"}

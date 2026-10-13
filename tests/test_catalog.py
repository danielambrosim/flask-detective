"""Catálogo de sites (data.json local)."""


def test_catalogo_carrega_sem_rede(catalog):
    assert len(catalog) > 300


def test_sites_nsfw_ficam_fora(catalog):
    assert all(not info.get("isNSFW") for info in catalog.sites.values())


def test_populares_existem_no_catalogo(catalog):
    popular = catalog.popular()
    assert popular, "a lista de populares não pode ficar vazia"
    assert all(name in catalog.sites for name in popular)
    # Facebook não existe no catálogo; a versão original oferecia mesmo assim
    assert "Facebook" not in popular


def test_resolve_case_insensitive(catalog):
    assert catalog.resolve("GITHUB") == "GitHub"
    assert catalog.resolve("nao-existe") is None
    assert catalog.resolve("") is None


def test_todo_site_usa_o_usuario_na_consulta(catalog):
    # A maioria tem "{}" na URL; alguns (ex.: Discord) consultam via POST com payload
    for name, info in catalog.sites.items():
        probe = info["url"] + str(info.get("urlProbe", "")) + str(info.get("request_payload", ""))
        assert "{}" in probe, name

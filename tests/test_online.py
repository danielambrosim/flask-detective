"""Busca real (precisa de internet). Rode com: pytest -m online"""
import time

import pytest

from sherlock_service import SearchManager, SiteCatalog


@pytest.mark.online
def test_busca_real_no_github():
    m = SearchManager(SiteCatalog(), site_timeout=15)
    job = m.start("torvalds", ["GitHub", "DeviantART"])
    end = time.time() + 60
    while job.active and time.time() < end:
        time.sleep(0.2)
    data = job.to_dict()
    assert data["status"] == "done"
    assert any(f["site"] == "GitHub" for f in data["found"])
    # sem lixo com códigos ANSI (bug da versão original)
    assert all("\x1b" not in f["url"] for f in data["found"])


@pytest.mark.online
def test_vinculo_real_entre_github_e_x():
    """A conta pública da Vercel declara no GitHub o perfil x.com/vercel."""
    from linking import LinkVerifier

    found = [
        {"site": "GitHub", "url": "https://www.github.com/vercel"},
        {"site": "Twitter", "url": "https://x.com/vercel"},
    ]
    out = LinkVerifier().verify("vercel", "GitHub", found)
    assert out["sites"]["Twitter"]["status"] == "confirmed"

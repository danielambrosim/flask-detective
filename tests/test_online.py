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

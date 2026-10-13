"""Execução das buscas em background."""
import time

import pytest

from sherlock_service import SearchManager, TooManySearches
from tests.conftest import FakeRunner


def wait(job, timeout=5):
    end = time.time() + timeout
    while job.active and time.time() < end:
        time.sleep(0.01)
    return job.to_dict()


def test_busca_coleta_somente_encontrados(manager):
    data = wait(manager.start("torvalds", ["GitHub", "Reddit", "Medium"]))
    assert data["status"] == "done"
    assert [r["site"] for r in data["found"]] == ["GitHub", "Reddit"]
    assert data["checked"] == data["total"] == 3
    assert data["progress"] == 100
    gh = data["found"][0]
    assert gh["url"] == "https://www.github.com/torvalds"
    assert gh["home"].startswith("https://")


def test_sem_sites_busca_catalogo_inteiro(manager, runner, catalog):
    wait(manager.start("abc", None))
    assert len(runner.calls[0]["sites"]) == len(catalog)


def test_falhas_sao_contadas(catalog):
    m = SearchManager(catalog, runner=FakeRunner(claimed=(), fail=("GitHub",)))
    data = wait(m.start("abc", ["GitHub", "Reddit"]))
    assert data["failed"] == 1 and data["found"] == []


def test_excecao_no_sherlock_vira_status_error(catalog):
    m = SearchManager(catalog, runner=FakeRunner(raise_exc=RuntimeError("boom")))
    data = wait(m.start("abc", ["GitHub"]))
    assert data["status"] == "error"
    assert "boom" not in data["error"]  # não vaza detalhes internos


def test_mesmo_cliente_nao_pode_ter_duas_buscas(catalog):
    r = FakeRunner()
    r.release.clear()
    m = SearchManager(catalog, runner=r)
    m.start("a", ["GitHub"], owner="1.2.3.4")
    with pytest.raises(TooManySearches):
        m.start("b", ["GitHub"], owner="1.2.3.4")
    m.start("c", ["GitHub"], owner="5.6.7.8")  # outro cliente pode
    r.release.set()


def test_limite_global_de_buscas(catalog):
    r = FakeRunner()
    r.release.clear()
    m = SearchManager(catalog, runner=r, max_pending=2)
    m.start("a", ["GitHub"], owner="1")
    m.start("b", ["GitHub"], owner="2")
    with pytest.raises(TooManySearches):
        m.start("c", ["GitHub"], owner="3")
    r.release.set()


def test_jobs_antigos_sao_removidos(catalog):
    m = SearchManager(catalog, runner=FakeRunner(), job_ttl=0)
    old = m.start("a", ["GitHub"])
    wait(old)
    m.start("b", ["GitHub"])
    assert m.get(old.id) is None


def test_progresso_parcial(catalog):
    m = SearchManager(catalog, runner=FakeRunner(delay=0.05))
    job = m.start("abc", catalog.names()[:20])
    time.sleep(0.3)
    snap = job.to_dict()
    assert 0 < snap["checked"] < 20 and snap["status"] == "running"
    assert wait(job)["checked"] == 20


def test_nao_grava_arquivos_no_disco(manager, tmp_path, monkeypatch):
    # O CLI original deixava <usuario>.txt no diretório atual a cada busca
    monkeypatch.chdir(tmp_path)
    wait(manager.start("torvalds", ["GitHub"]))
    assert list(tmp_path.iterdir()) == []

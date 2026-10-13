import os
import sys
import threading
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import create_app  # noqa: E402
from extensions import db, limiter  # noqa: E402
from sherlock_service import SearchManager, SiteCatalog  # noqa: E402
from sherlock_project.result import QueryResult, QueryStatus  # noqa: E402


class FakeRunner:
    """Simula o Sherlock: o usuário "existe" nos sites listados em `claimed`."""

    def __init__(self, claimed=("GitHub", "Reddit"), fail=(), delay=0.0, raise_exc=None):
        self.claimed = set(claimed)
        self.fail = set(fail)
        self.delay = delay
        self.raise_exc = raise_exc
        self.calls = []
        self.release = threading.Event()
        self.release.set()

    def __call__(self, username, site_data, notify, timeout):
        self.calls.append({"username": username, "sites": list(site_data), "timeout": timeout})
        self.release.wait(5)
        if self.raise_exc:
            raise self.raise_exc
        notify.start(username)
        for name, info in site_data.items():
            if self.delay:
                time.sleep(self.delay)
            if name in self.claimed:
                status = QueryStatus.CLAIMED
            elif name in self.fail:
                status = QueryStatus.UNKNOWN
            else:
                status = QueryStatus.AVAILABLE
            url = info["url"].replace("{}", username)
            notify.update(QueryResult(username, name, url, status, query_time=0.123))
        return {}


@pytest.fixture(scope="session")
def catalog():
    return SiteCatalog()


@pytest.fixture
def runner():
    return FakeRunner()


@pytest.fixture
def manager(catalog, runner):
    return SearchManager(catalog, runner=runner, max_workers=2, max_pending=3)


TEST_CONFIG = {
    "TESTING": True,
    "SECRET_KEY": "chave-de-teste",
    "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
    "WTF_CSRF_ENABLED": False,
    "RATELIMIT_ENABLED": False,
}


def make_app(manager, **overrides):
    app = create_app(manager, config={**TEST_CONFIG, **overrides})
    with app.app_context():
        db.create_all()
    limiter.reset()
    return app


@pytest.fixture
def app(manager):
    app = make_app(manager)
    yield app
    with app.app_context():
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def wait_job(client, job_id, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"/api/search/{job_id}").get_json()
        if data["status"] in ("done", "error"):
            return data
        time.sleep(0.02)
    raise AssertionError("job não terminou a tempo")

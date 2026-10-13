"""Integração com o Sherlock.

Usa a API Python do Sherlock (cópia em ./sherlock) em vez de chamar o script via
subprocess. Isso elimina injeção de argumentos, parsing frágil de stdout com
códigos ANSI, arquivos ``<usuario>.txt`` gravados no disco e o download do
catálogo de sites a cada busca.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SHERLOCK_DIR = os.path.join(BASE_DIR, "sherlock")
DATA_FILE = os.path.join(SHERLOCK_DIR, "sherlock_project", "resources", "data.json")

# A cópia local tem prioridade sobre qualquer sherlock-project instalado via pip,
# garantindo que código e catálogo (data.json) sejam da mesma versão.
if SHERLOCK_DIR not in sys.path:
    sys.path.insert(0, SHERLOCK_DIR)

from sherlock_project.notify import QueryNotify  # noqa: E402
from sherlock_project.result import QueryStatus  # noqa: E402

# Não pode começar com "-" ou "." (evita confusão com flags e nomes inválidos).
USERNAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,49}$")

# Sites exibidos como atalho na interface. Só entram os que existem no catálogo.
POPULAR_SITES = [
    "Instagram", "Twitter", "TikTok", "GitHub", "Reddit", "YouTube",
    "Medium", "Pinterest", "DeviantArt", "Twitch", "Spotify", "LinkedIn",
    "Telegram", "Steam", "SoundCloud", "Patreon",
]

MAX_SELECTED_SITES = 60


class ValidationError(ValueError):
    """Entrada do usuário inválida (mensagem pronta para exibir)."""


# --------------------------------------------------------------------------- #
# Catálogo de sites
# --------------------------------------------------------------------------- #
class SiteCatalog:
    def __init__(self, data_file: str = DATA_FILE, include_nsfw: bool = False):
        with open(data_file, encoding="utf-8") as fh:
            raw = json.load(fh)
        raw.pop("$schema", None)
        self.sites: dict[str, dict] = {
            name: info
            for name, info in raw.items()
            if isinstance(info, dict) and (include_nsfw or not info.get("isNSFW"))
        }
        self._by_lower = {name.lower(): name for name in self.sites}

    def __len__(self) -> int:
        return len(self.sites)

    def names(self) -> list[str]:
        return sorted(self.sites, key=str.lower)

    def popular(self) -> list[str]:
        return [self._by_lower[s.lower()] for s in POPULAR_SITES if s.lower() in self._by_lower]

    def resolve(self, name: str) -> str | None:
        """Nome canônico (com a grafia do catálogo) ou None se não existir."""
        return self._by_lower.get((name or "").strip().lower())

    def subset(self, names: list[str] | None) -> dict[str, dict]:
        if not names:
            return dict(self.sites)
        return {n: self.sites[n] for n in names}


# --------------------------------------------------------------------------- #
# Validação
# --------------------------------------------------------------------------- #
def normalize_username(value: str | None) -> str:
    username = (value or "").strip().lstrip("@").strip()
    if not username:
        raise ValidationError("Digite um nome de usuário.")
    if not USERNAME_RE.match(username):
        raise ValidationError(
            "Usuário inválido. Use até 50 caracteres: letras, números, ponto, hífen "
            "e underline (sem começar com ponto ou hífen)."
        )
    return username


def normalize_sites(catalog: SiteCatalog, mode: str | None, sites: list[str] | None) -> list[str] | None:
    """Retorna None para "todos os sites" ou a lista canônica de sites escolhidos."""
    if mode in (None, "", "all"):
        return None
    if mode != "custom":
        raise ValidationError("Modo de busca inválido.")

    resolved: list[str] = []
    unknown: list[str] = []
    for s in sites or []:
        canonical = catalog.resolve(s)
        if canonical is None:
            unknown.append(str(s)[:40])
        elif canonical not in resolved:
            resolved.append(canonical)

    if unknown:
        raise ValidationError("Site(s) não suportado(s): " + ", ".join(unknown) + ".")
    if not resolved:
        raise ValidationError("Selecione pelo menos um site.")
    if len(resolved) > MAX_SELECTED_SITES:
        raise ValidationError(f"Selecione no máximo {MAX_SELECTED_SITES} sites.")
    return resolved


# --------------------------------------------------------------------------- #
# Jobs de busca (rodam em background; o front-end consulta o progresso)
# --------------------------------------------------------------------------- #
@dataclass
class SearchJob:
    username: str
    sites: list[str] | None
    total: int
    owner: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: str = "queued"  # queued | running | done | error
    checked: int = 0
    found: list[dict] = field(default_factory=list)
    failed: int = 0
    error: str | None = None
    created_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def active(self) -> bool:
        return self.status in ("queued", "running")

    def to_dict(self) -> dict:
        with self.lock:
            end = self.finished_at or time.monotonic()
            return {
                "id": self.id,
                "username": self.username,
                "status": self.status,
                "total": self.total,
                "checked": self.checked,
                "progress": round(100 * self.checked / self.total) if self.total else 100,
                "found": sorted(self.found, key=lambda r: r["site"].lower()),
                "failed": self.failed,
                "error": self.error,
                "elapsed": round(end - self.created_at, 1),
            }


class _ProgressNotify(QueryNotify):
    """Recebe cada resultado do Sherlock e atualiza o job."""

    def __init__(self, job: SearchJob, catalog: SiteCatalog):
        super().__init__()
        self.job = job
        self.catalog = catalog

    def update(self, result):
        with self.job.lock:
            self.job.checked += 1
            if result.status == QueryStatus.CLAIMED:
                info = self.catalog.sites.get(result.site_name, {})
                self.job.found.append({
                    "site": result.site_name,
                    "url": result.site_url_user,
                    "home": info.get("urlMain", ""),
                    "time": round(result.query_time, 2) if result.query_time else None,
                })
            elif result.status in (QueryStatus.UNKNOWN, QueryStatus.WAF):
                self.job.failed += 1


def _default_runner(username, site_data, notify, timeout):
    from sherlock_project.sherlock import sherlock

    return sherlock(username, site_data, notify, timeout=timeout)


class TooManySearches(RuntimeError):
    pass


class SearchManager:
    def __init__(
        self,
        catalog: SiteCatalog,
        runner=_default_runner,
        max_workers: int = 2,
        max_pending: int = 6,
        site_timeout: int = 15,
        job_ttl: int = 15 * 60,
    ):
        self.catalog = catalog
        self.runner = runner
        self.site_timeout = site_timeout
        self.max_pending = max_pending
        self.job_ttl = job_ttl
        self.jobs: dict[str, SearchJob] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="sherlock")

    def _purge(self) -> None:
        now = time.monotonic()
        for jid in [j.id for j in self.jobs.values()
                    if not j.active and j.finished_at and now - j.finished_at > self.job_ttl]:
            del self.jobs[jid]

    def start(self, username: str, sites: list[str] | None, owner: str = "") -> SearchJob:
        site_data = self.catalog.subset(sites)
        job = SearchJob(username=username, sites=sites, total=len(site_data), owner=owner)
        with self._lock:
            self._purge()
            active = [j for j in self.jobs.values() if j.active]
            if owner and any(j.owner == owner for j in active):
                raise TooManySearches("Você já tem uma busca em andamento. Aguarde ela terminar.")
            if len(active) >= self.max_pending:
                raise TooManySearches("Servidor ocupado no momento. Tente novamente em instantes.")
            self.jobs[job.id] = job
        self._pool.submit(self._run, job, site_data)
        return job

    def _run(self, job: SearchJob, site_data: dict) -> None:
        with job.lock:
            job.status = "running"
        try:
            self.runner(job.username, site_data, _ProgressNotify(job, self.catalog), self.site_timeout)
            with job.lock:
                job.checked = job.total
                job.status = "done"
        except Exception as exc:  # noqa: BLE001 - qualquer falha vira status de erro
            with job.lock:
                job.status = "error"
                job.error = "A busca falhou inesperadamente. Tente novamente."
            print(f"[sherlock] job {job.id} falhou: {exc!r}", file=sys.stderr)
        finally:
            with job.lock:
                job.finished_at = time.monotonic()

    def get(self, job_id: str) -> SearchJob | None:
        with self._lock:
            return self.jobs.get(job_id)

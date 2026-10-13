"""Verificação de vínculo entre perfis.

O Sherlock só diz que um nome de usuário *existe* em um site, não que pertence à
mesma pessoa. Aqui procuramos evidência pública: um perfil que aponta para outro
(link na bio, rel="me", contas sociais declaradas no GitHub). Como é a própria
pessoa que publica esses links, eles são a prova mais confiável disponível.

Status por site:
  seed        -> perfil de referência escolhido pelo usuário
  confirmed   -> há link direto entre ele e o perfil de referência
  probable    -> ligado (por links) a um perfil já confirmado
  unverified  -> nenhuma evidência pública; pode ser outra pessoa (homônimo)

Segurança: só buscamos as URLs de perfil geradas pelo Sherlock (nunca links
encontrados nas páginas), então não há como forçar o servidor a acessar URLs
arbitrárias.
"""

from __future__ import annotations

import html
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
MAX_BYTES = 1_500_000

# Domínios equivalentes (o mesmo serviço com outro endereço).
HOST_ALIASES = {
    "twitter.com": "x.com",
    "fxtwitter.com": "x.com",
    "youtu.be": "youtube.com",
    "instagr.am": "instagram.com",
    "fb.com": "facebook.com",
}
_HOST_PREFIXES = ("www.", "m.", "mobile.", "web.")

_URL_RE = re.compile(r"""https?:(?:\\?/){2}[^\s"'<>()\[\]{}|\\^`]+""", re.I)


def normalize_host(host: str) -> str:
    host = (host or "").lower().split(":")[0].rstrip(".")
    for prefix in _HOST_PREFIXES:
        if host.startswith(prefix):
            host = host[len(prefix):]
            break
    return HOST_ALIASES.get(host, host)


def extract_links(page: str) -> set[str]:
    """Todas as URLs http(s) da página: href, rel="me", texto e JSON embutido."""
    if not page:
        return set()
    text = html.unescape(page).replace("\\/", "/").replace("\\u002F", "/").replace("\\u002f", "/")
    return {m.rstrip(".,;:!?") for m in _URL_RE.findall(text)}


def _segments(url: str) -> tuple[str, str, list[str]]:
    parts = urlsplit(url)
    raw_host = (parts.hostname or "").lower()
    path = [s.lstrip("@").lower() for s in parts.path.split("/") if s]
    return normalize_host(raw_host), raw_host, path


def link_points_to(link: str, profile_url: str, username: str) -> bool:
    """O link aponta para o perfil `profile_url` do usuário `username`?

    Compara o domínio (com aliases, ex.: twitter.com == x.com) e exige o nome de
    usuário como segmento do caminho (x.com/maria) ou subdomínio (maria.site.com).
    """
    try:
        link_host, link_raw_host, link_path = _segments(link)
        prof_host, _, _ = _segments(profile_url)
    except ValueError:
        return False
    user = username.lower()
    same_site = link_host == prof_host or link_host.endswith("." + prof_host)
    if not same_site:
        return False
    return user in link_path or link_raw_host.startswith(user + ".")


class LinkVerifier:
    def __init__(self, fetch_page=None, fetch_json=None, max_pages: int = 40, workers: int = 8, timeout: int = 8):
        self.fetch_page = fetch_page or self._http_page
        self.fetch_json = fetch_json or self._http_json
        self.max_pages = max_pages
        self.workers = workers
        self.timeout = timeout

    # ------------------------------------------------------------------ HTTP
    def _http_page(self, url: str) -> str:
        with requests.get(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,en;q=0.8"},
                          timeout=self.timeout, stream=True) as r:
            if r.status_code >= 400:
                return ""
            data = r.raw.read(MAX_BYTES, decode_content=True)
            return data.decode(r.encoding or "utf-8", errors="replace")

    def _http_json(self, url: str):
        r = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
                         timeout=self.timeout)
        return r.json() if r.status_code == 200 else None

    # ------------------------------------------------------------- coleta
    def _outlinks(self, result: dict, username: str) -> set[str]:
        links: set[str] = set()
        try:
            links |= extract_links(self.fetch_page(result["url"]))
        except Exception:  # noqa: BLE001 - site fora do ar não derruba a verificação
            pass
        if normalize_host(urlsplit(result["url"]).hostname or "") == "github.com":
            links |= self._github_links(username)
        return links

    def _github_links(self, username: str) -> set[str]:
        """Contas sociais que o dono declarou no GitHub (API pública)."""
        links: set[str] = set()
        try:
            for acc in self.fetch_json(f"https://api.github.com/users/{username}/social_accounts") or []:
                if isinstance(acc, dict) and isinstance(acc.get("url"), str):
                    links.add(acc["url"])
            user = self.fetch_json(f"https://api.github.com/users/{username}") or {}
            if user.get("twitter_username"):
                links.add(f"https://x.com/{user['twitter_username']}")
            if isinstance(user.get("blog"), str) and user["blog"]:
                links.add(user["blog"] if "://" in user["blog"] else "https://" + user["blog"])
        except Exception:  # noqa: BLE001
            pass
        return links

    # ------------------------------------------------------------ análise
    def verify(self, username: str, seed_site: str, found: list[dict]) -> dict:
        by_site = {r["site"]: r for r in found}
        if seed_site not in by_site:
            raise ValueError("O perfil de referência precisa estar entre os encontrados.")

        others = [r for r in found if r["site"] != seed_site][: self.max_pages - 1]
        targets = [by_site[seed_site]] + others
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            outlinks = dict(zip([r["site"] for r in targets],
                                pool.map(lambda r: self._outlinks(r, username), targets)))

        def host_of(site):
            return normalize_host(urlsplit(by_site[site]["url"]).hostname or "")

        def points(a: str, b: str) -> bool:
            if host_of(a) == host_of(b):  # links internos do próprio site não contam
                return False
            return any(link_points_to(link, by_site[b]["url"], username) for link in outlinks.get(a, ()))

        sites = [r["site"] for r in targets]
        result = {s: {"status": "unverified", "evidence": "Nenhum link público entre este perfil e os demais."}
                  for s in by_site}
        result[seed_site] = {"status": "seed", "evidence": "Perfil de referência."}

        confirmed: list[str] = []
        for s in sites:
            if s == seed_site:
                continue
            if points(seed_site, s):
                result[s] = {"status": "confirmed", "evidence": f"O perfil no {seed_site} aponta para este."}
            elif points(s, seed_site):
                result[s] = {"status": "confirmed", "evidence": f"Este perfil aponta para o {seed_site}."}
            else:
                continue
            confirmed.append(s)

        # Propaga: ligado a um confirmado -> provável (busca em largura)
        queue = list(confirmed)
        while queue:
            anchor = queue.pop(0)
            for s in sites:
                if result[s]["status"] != "unverified":
                    continue
                if points(anchor, s) or points(s, anchor):
                    result[s] = {"status": "probable", "evidence": f"Ligado ao perfil no {anchor} (já confirmado)."}
                    queue.append(s)

        for s in by_site:
            if s not in outlinks and result[s]["status"] == "unverified":
                result[s]["evidence"] = "Não verificado (limite de páginas atingido)."

        return {
            "seed": seed_site,
            "seed_links": len(outlinks.get(seed_site, ())),
            "checked": len(targets),
            "sites": result,
        }

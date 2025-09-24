import os, sys, subprocess, re, html
from flask import Flask, render_template, request
from markupsafe import Markup

app = Flask(__name__)

BASE_DIR = os.path.dirname(__file__)
CANDIDATES = [
    os.path.join(BASE_DIR, "sherlock", "sherlock_project", "sherlock.py"),  # seu caso atual
    os.path.join(BASE_DIR, "sherlock", "sherlock.py"),
    os.path.join(BASE_DIR, "sherlock-master", "sherlock.py"),
]
SHERLOCK_PATH = next((p for p in CANDIDATES if os.path.isfile(p)), None)
if not SHERLOCK_PATH:
    raise RuntimeError("Não encontrei sherlock.py. Coloque o repositório em ./sherlock/")

USERNAME_RE = re.compile(r'^[A-Za-z0-9._-]{1,50}$')  # username genérico

# Lista “curta” de sites com nomes como o Sherlock entende (sensível a maiúsculas em alguns casos)
KNOWN_SITES = [
    "Instagram", "Twitter", "TikTok", "GitHub", "Reddit",
    "Facebook", "YouTube", "Medium", "Pinterest", "DeviantArt"
]

def run_sherlock(username: str, sites: list[str] | None, timeout_s: int = 25) -> dict:
    """
    Roda o Sherlock; se 'sites' vier vazio/None, pesquisa em todos.
    Retorna dict com urls encontradas e stdout/stderr para diagnóstico.
    """
    env = os.environ.copy()
    # alguns ambientes dão menos problema com HTTP/1.1
    env.setdefault("GIT_HTTP_VERSION", "HTTP/1.1")

    cmd = [sys.executable, SHERLOCK_PATH, username, "--print-found", "--timeout", str(timeout_s)]

    if sites:
        # o Sherlock aceita repetir --site para filtrar; nomes devem bater com o catálogo interno
        for s in sites:
            s_clean = s.strip()
            if s_clean:
                cmd += ["--site", s_clean]

    run = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
    stdout = (run.stdout or "").strip()
    stderr = (run.stderr or "").strip()

    # Extrair URLs encontradas (linhas que contenham http/https)
    urls = []
    for line in stdout.splitlines():
        line = line.strip()
        i = line.find("http")
        if i != -1:
            url = line[i:].strip()
            # heurística leve: filtra lixo e duplica
            if url.startswith(("http://", "https://")) and len(url) < 2048:
                urls.append(url)

    # dedup mantendo ordem
    seen = set()
    unique_urls = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            unique_urls.append(u)

    # tentar inferir nome do site a partir do domínio (só pra exibir bonitinho)
    def site_label(u: str) -> str:
        # pega domínio base
        m = re.search(r'https?://([^/]+)/?', u)
        host = m.group(1).lower() if m else ""
        mapping = {
            "instagram.com": "Instagram",
            "twitter.com": "Twitter",
            "x.com": "Twitter",
            "tiktok.com": "TikTok",
            "github.com": "GitHub",
            "reddit.com": "Reddit",
            "facebook.com": "Facebook",
            "m.facebook.com": "Facebook",
            "youtube.com": "YouTube",
            "medium.com": "Medium",
            "pinterest.com": "Pinterest",
            "deviantart.com": "DeviantArt",
        }
        for k, v in mapping.items():
            if host.endswith(k):
                return v
        return host or "Site"

    results = [{"site": site_label(u), "url": u} for u in unique_urls]

    return {
        "ok": run.returncode == 0 or bool(results),  # alguns sites não achados retornam rc != 0
        "results": results,
        "stdout": stdout,
        "stderr": stderr,
        "returncode": run.returncode,
        "cmd": " ".join(cmd),
    }

@app.route("/", methods=["GET", "POST"])
def index():
    data = {
        "username": "",
        "selected_sites": [],
        "search_all": True,
        "known_sites": KNOWN_SITES,
        "result": None,
        "error": None,
        "debug": False,
    }

    if request.method == "POST":
        data["username"] = (request.form.get("username") or "").strip().lstrip("@")
        data["search_all"] = (request.form.get("mode") == "all")
        data["selected_sites"] = request.form.getlist("sites")
        data["debug"] = (request.form.get("debug") == "on")

        if not data["username"]:
            data["error"] = "Digite um nome de usuário."
        elif not USERNAME_RE.match(data["username"]):
            data["error"] = "Usuário inválido. Use letras, números, ponto, hífen e underline."
        else:
            sites = None if data["search_all"] else data["selected_sites"]
            r = run_sherlock(data["username"], sites=sites, timeout_s=30)
            if not r.get("ok") and not r.get("results"):
                data["error"] = "Não foi possível obter resultados. Veja detalhes de diagnóstico abaixo."
            else:
                data["result"] = r

    return render_template("index.html", **data)

if __name__ == "__main__":
    # Rode: python app.py
    app.run(host="0.0.0.0", port=5000, debug=True)  
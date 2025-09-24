from flask import Flask, render_template, request
from markupsafe import Markup
import re, subprocess, sys, os

app = Flask(__name__)

# Caminho do script do Sherlock
SHERLOCK_PATH = os.path.join(os.path.dirname(__file__), "sherlock", "sherlock.py")

# Validação simples para @ de Instagram
INSTAGRAM_RE = re.compile(r'^[A-Za-z0-9._]{1,30}$')

def check_instagram(username: str) -> dict:
    """
    Chama o Sherlock restrito ao site Instagram e retorna um dicionário com o resultado.
    """
    # Comando:
    # --site instagram   limita só ao Instagram
    # --print-found      imprime apenas sites encontrados
    # --timeout 15       evita travar por muito tempo
    cmd = [sys.executable, SHERLOCK_PATH, username, "--site", "instagram", "--print-found", "--timeout", "15"]

    try:
        run = subprocess.run(cmd, capture_output=True, text=True, check=False)
        stdout = run.stdout.strip()
        stderr = run.stderr.strip()

        # Se o usuário existir no Instagram, o Sherlock costuma imprimir a URL encontrada
        found_url = None
        for line in stdout.splitlines():
            line = line.strip()
            if "instagram.com" in line:
                # pode vir como URL puro ou como "instagram: https://..."
                # pegamos o primeiro http(s)
                http_idx = line.find("http")
                if http_idx != -1:
                    found_url = line[http_idx:].strip()
                    break

        return {
            "ok": True,
            "exists": found_url is not None,
            "url": found_url,
            "raw_out": stdout,
            "raw_err": stderr,
            "returncode": run.returncode
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    username = ""
    error = None

    if request.method == "POST":
        username = request.form.get("username", "").strip().lstrip("@")

        if not username:
            error = "Digite um nome de usuário."
        elif not INSTAGRAM_RE.match(username):
            error = "Usuário inválido. Use apenas letras, números, ponto e underline (máx. 30)."
        else:
            r = check_instagram(username)
            if not r.get("ok"):
                error = f"Erro ao consultar: {r.get('error','desconhecido')}"
            else:
                if r["exists"]:
                    result = {
                        "status": "encontrado",
                        "message": Markup(f"✅ Encontrado: <a href='{r['url']}' target='_blank'>{r['url']}</a>")
                    }
                else:
                    result = {
                        "status": "nao_encontrado",
                        "message": "❌ Não encontrado no Instagram (pelo Sherlock)."
                    }

    return render_template("index.html", result=result, username=username, error=error)

if __name__ == "__main__":
    # Rode: python app.py
    app.run(host="0.0.0.0", port=5000, debug=True)

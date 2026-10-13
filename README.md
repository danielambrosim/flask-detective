# Detective — Sherlock Flask

Aplicação web em **Flask** que usa o **[Sherlock](https://github.com/sherlock-project/sherlock)** para procurar um nome de usuário em centenas de sites e redes sociais (OSINT).

## Recursos

* Busca em todos os ~400 sites do catálogo ou só nos que você escolher (atalhos para os populares e filtro por nome).
* Progresso real em tempo real: a busca roda em segundo plano e a página consulta o andamento, sem estourar o timeout do servidor.
* Resultados em cards, com filtro, botão para copiar os links e exportação em CSV.
* Layout responsivo (celular, tablet e desktop).
* Validação de entrada, limite de buscas simultâneas e cabeçalhos de segurança (CSP etc.).
* **Verificação de vínculo:** escolha um perfil de referência (ex.: o Instagram que você conhece) e veja quais outros resultados estão ligados a ele.

## Verificação de vínculo entre perfis

O Sherlock só informa que um nome de usuário **existe** em um site, não que é a mesma pessoa. Na busca por "torvalds", por exemplo, a maioria dos resultados é de homônimos. O `linking.py` procura evidência pública de que os perfis são da mesma pessoa: links na bio, `rel="me"` e contas sociais declaradas na API do GitHub.

| Selo | Significado |
|---|---|
| Referência | Perfil escolhido por você |
| Vinculado | Ele aponta para a referência, ou a referência aponta para ele |
| Provável | Ligado por links a um perfil já vinculado |
| Não comprovado | Nenhum link público; pode ser outra pessoa com o mesmo nome |

Limitações: Instagram, X, YouTube e TikTok não mostram bio nem links sem login, então como referência eles raramente comprovam algo. Funcionam melhor como referência GitHub, Mastodon, Keybase e sites pessoais. Só são acessadas as URLs de perfil geradas pelo Sherlock (nunca links encontrados nas páginas).

API: `POST /api/search/<id>/verify` com `{"seed": "GitHub"}`. O resultado aparece no campo `verify` de `GET /api/search/<id>`.

## Estrutura

```
app.py                # rotas Flask (página + API JSON)
sherlock_service.py   # catálogo de sites, validação e execução das buscas
sherlock/             # cópia do Sherlock (código + data.json)
templates/            # index.html e 404.html
static/               # css, js e favicon
tests/                # testes automatizados (pytest)
gunicorn.conf.py      # configuração usada em produção
```

## Rodando localmente

```bash
git clone https://github.com/danielambrosim/flask-detective.git
cd flask-detective
python -m venv .venv
# Linux/macOS: source .venv/bin/activate   |   Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Abra http://127.0.0.1:5000. Para ligar o modo debug do Flask: `FLASK_DEBUG=1 python app.py` (nunca em produção).

## API

| Método | Rota | Descrição |
|---|---|---|
| `POST` | `/api/search` | Corpo `{"username": "torvalds", "mode": "all"}` ou `{"username": "...", "mode": "custom", "sites": ["GitHub", "Reddit"]}`. Retorna `202` com o `id` da busca. |
| `GET` | `/api/search/<id>` | Status, progresso (`checked`/`total`) e perfis encontrados (`found`). |
| `GET` | `/healthz` | Health check. |

Erros: `400` (entrada inválida), `404` (busca expirada), `429` (busca já em andamento / servidor ocupado).

## Testes

```bash
pip install -r requirements-dev.txt
pytest              # testes offline (o Sherlock é simulado)
pytest -m online    # busca real na internet
```

## Deploy (Render)

* **Build command:** `pip install -r requirements.txt`
* **Start command:** `gunicorn app:app`

O `gunicorn.conf.py` é lido automaticamente e usa **1 worker com várias threads**: as buscas ficam em memória, então vários workers fariam o polling cair em processos que não conhecem a busca.

Variáveis de ambiente opcionais: `SEARCH_WORKERS` (buscas em paralelo, padrão 2), `SITE_TIMEOUT` (segundos por site, padrão 15), `GUNICORN_THREADS` (padrão 8).

## Uso responsável

Os resultados dependem da disponibilidade dos sites e de bloqueios anti-bot, e podem conter falsos positivos. Use somente para fins legítimos, respeitando a privacidade e a LGPD.

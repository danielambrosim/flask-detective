# Lido automaticamente pelo gunicorn (ex.: `gunicorn app:app` no Render).
# As buscas ficam em memória, então usamos 1 processo com várias threads:
# com mais de um worker, o polling poderia cair num processo que não conhece o job.
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '10000')}"
workers = 1
threads = int(os.environ.get("GUNICORN_THREADS", 8))
timeout = 60

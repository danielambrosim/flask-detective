"""Extensões Flask compartilhadas (inicializadas em create_app)."""
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()
login_manager = LoginManager()
# Memória basta: o app roda em 1 processo (ver gunicorn.conf.py).
limiter = Limiter(key_func=get_remote_address, storage_uri="memory://", default_limits=[])

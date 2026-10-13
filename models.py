from datetime import datetime, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from flask_login import UserMixin

from extensions import db

_hasher = PasswordHasher()  # argon2id com parâmetros recomendados


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), nullable=False)
    email = db.Column(db.String(254), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    def set_password(self, password: str) -> None:
        self.password_hash = _hasher.hash(password)

    def check_password(self, password: str) -> bool:
        try:
            ok = _hasher.verify(self.password_hash, password)
        except (VerificationError, InvalidHashError):
            return False
        if ok and _hasher.check_needs_rehash(self.password_hash):
            self.password_hash = _hasher.hash(password)
            db.session.commit()
        return ok

    @property
    def first_name(self) -> str:
        return self.name.split()[0]


# Hash fixo usado quando o e-mail não existe, para o login levar o mesmo tempo
# nos dois casos (evita descobrir e-mails cadastrados pelo tempo de resposta).
DUMMY_HASH = _hasher.hash("senha-inexistente-para-equalizar-tempo")


def dummy_verify(password: str) -> None:
    try:
        _hasher.verify(DUMMY_HASH, password)
    except VerificationError:
        pass

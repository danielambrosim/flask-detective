"""Login, cadastro e logout."""
from urllib.parse import urlsplit

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from flask_wtf import FlaskForm
from sqlalchemy.exc import IntegrityError
from wtforms import BooleanField, EmailField, PasswordField, StringField
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError

from extensions import db, limiter
from models import User, dummy_verify

bp = Blueprint("auth", __name__)

PASSWORD_MIN = 8
PASSWORD_MAX = 128


def _strip(value):
    return value.strip() if isinstance(value, str) else value


def _lower(value):
    return value.strip().lower() if isinstance(value, str) else value


class LoginForm(FlaskForm):
    email = EmailField("E-mail", filters=[_lower], validators=[
        DataRequired("Informe seu e-mail."),
        Email("E-mail inválido.", check_deliverability=False),
        Length(max=254),
    ])
    password = PasswordField("Senha", validators=[DataRequired("Informe sua senha."), Length(max=PASSWORD_MAX)])
    remember = BooleanField("Manter conectado")


class SignupForm(FlaskForm):
    name = StringField("Nome", filters=[_strip], validators=[
        DataRequired("Informe seu nome."),
        Length(min=2, max=60, message="O nome deve ter entre 2 e 60 caracteres."),
    ])
    email = EmailField("E-mail", filters=[_lower], validators=[
        DataRequired("Informe seu e-mail."),
        Email("E-mail inválido.", check_deliverability=False),
        Length(max=254),
    ])
    password = PasswordField("Senha", validators=[
        DataRequired("Crie uma senha."),
        Length(min=PASSWORD_MIN, max=PASSWORD_MAX,
               message=f"A senha deve ter entre {PASSWORD_MIN} e {PASSWORD_MAX} caracteres."),
    ])
    confirm = PasswordField("Confirmar senha", validators=[
        DataRequired("Confirme a senha."),
        EqualTo("password", "As senhas não conferem."),
    ])

    def validate_password(self, field):
        pw = field.data or ""
        if not (any(c.isalpha() for c in pw) and any(c.isdigit() for c in pw)):
            raise ValidationError("Use letras e números na senha.")
        if self.email.data and pw.lower() == self.email.data.lower():
            raise ValidationError("A senha não pode ser igual ao e-mail.")


def safe_next(target: str | None) -> str:
    """Só aceita caminhos internos (evita open redirect, ex.: ?next=https://golpe.com)."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return url_for("index")
    parts = urlsplit(target)
    if parts.scheme or parts.netloc:
        return url_for("index")
    return target


def _start_session(user: User, remember: bool) -> None:
    session.clear()  # nova sessão a cada login (evita fixação de sessão)
    login_user(user, remember=remember)


@bp.route("/entrar", methods=["GET", "POST"])
@limiter.limit("10 per minute; 50 per hour", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    form = LoginForm()
    next_url = request.args.get("next")
    if form.validate_on_submit():
        user = db.session.execute(db.select(User).filter_by(email=form.email.data)).scalar_one_or_none()
        if user is None:
            dummy_verify(form.password.data)
        elif user.check_password(form.password.data):
            _start_session(user, form.remember.data)
            flash(f"Bem-vindo de volta, {user.first_name}!", "success")
            return redirect(safe_next(next_url))
        # Mesma mensagem nos dois casos: não revela se o e-mail existe
        form.form_errors.append("E-mail ou senha incorretos.")
    status = 400 if request.method == "POST" else 200
    return render_template("auth/login.html", form=form, next_url=next_url), status


@bp.route("/cadastrar", methods=["GET", "POST"])
@limiter.limit("5 per minute; 20 per hour", methods=["POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    form = SignupForm()
    next_url = request.args.get("next")
    if form.validate_on_submit():
        user = User(name=form.name.data, email=form.email.data)
        user.set_password(form.password.data)
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            form.email.errors = [*form.email.errors, "Já existe uma conta com esse e-mail. Tente entrar."]
        else:
            _start_session(user, remember=False)
            flash(f"Conta criada! Bem-vindo, {user.first_name}.", "success")
            return redirect(safe_next(next_url))
    status = 400 if request.method == "POST" else 200
    return render_template("auth/signup.html", form=form, next_url=next_url), status


@bp.post("/sair")
@login_required
def logout():
    logout_user()
    session.clear()
    flash("Você saiu da sua conta.", "info")
    return redirect(url_for("index"))


def handle_rate_limit(_):
    return render_template("auth/rate_limited.html"), 429

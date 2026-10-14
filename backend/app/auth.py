import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import get_db
from .models import AuditEvent, LoginAttempt, LoginSession, Professional, User

router = APIRouter(prefix="/api/auth", tags=["Authentication"])
Db = Annotated[Session, Depends(get_db)]


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
    return f"scrypt${salt}${digest}"


def verify_password(password: str, encoded: str) -> bool:
    _, salt, expected = encoded.split("$")
    actual = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
    return hmac.compare_digest(actual, expected)


def user_data(user: User):
    return dict(id=user.id, username=user.username, name=user.name, role=user.role,
                professional_id=user.professional_id, active=user.active)


def current_user(db: Db, authorization: Annotated[str | None, Header()] = None) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Entre com seu usuário e senha")
    session = db.get(LoginSession, token_hash(authorization[7:]))
    now = datetime.now(timezone.utc)
    if session is None or utc(session.expires_at) <= now:
        raise HTTPException(401, "Sessão expirada; entre novamente")
    user = db.get(User, session.user_id)
    if user is None or not user.active:
        raise HTTPException(401, "Usuário inativo")
    return user


Actor = Annotated[User, Depends(current_user)]


def staff(actor: Actor):
    if actor.role not in ("admin", "reception"):
        raise HTTPException(403, "Acesso restrito à administração e recepção")
    return actor


def administrator(actor: Actor):
    if actor.role != "admin":
        raise HTTPException(403, "Acesso restrito à administração")
    return actor


def professional_scope(actor: User, professional_id: int | None) -> int | None:
    if actor.role == "barber":
        if professional_id is not None and professional_id != actor.professional_id:
            raise HTTPException(403, "Você pode acessar apenas sua própria agenda")
        return actor.professional_id
    return professional_id


def audit(db: Session, action: str, entity_id: int | None = None, actor: User | None = None):
    db.add(AuditEvent(action=action, entity_id=entity_id, actor_id=actor.id if actor else None,
                      created_at=datetime.now(timezone.utc)))


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=128)


class UserInput(BaseModel):
    username: str = Field(min_length=3, max_length=120, pattern=r"^[a-zA-Z0-9_.@-]+$")
    name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=12, max_length=128)
    role: Literal["admin", "reception", "barber"]
    professional_id: int | None = None


def add_user(data: UserInput, db: Session) -> User:
    if data.role == "barber" and (data.professional_id is None or db.get(Professional, data.professional_id) is None):
        raise HTTPException(422, "Associe o barbeiro a um profissional cadastrado")
    user = User(username=data.username.lower(), name=data.name.strip(), password_hash=hash_password(data.password),
                role=data.role, professional_id=data.professional_id if data.role == "barber" else None)
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Este usuário já existe") from None
    return user


@router.post("/bootstrap", status_code=201)
def bootstrap(data: UserInput, db: Db, bootstrap_key: Annotated[str | None, Header()] = None):
    expected = os.getenv("BARBERFLOW_BOOTSTRAP_KEY", "")
    if not expected or not bootstrap_key or not hmac.compare_digest(expected, bootstrap_key):
        raise HTTPException(403, "Chave de configuração inválida")
    # PostgreSQL advisory lock also covers the empty-table first-user race.
    from sqlalchemy import text
    if db.bind.dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))
    else:
        db.execute(text("SELECT pg_advisory_xact_lock(73481292)"))
    if db.scalar(select(User.id).limit(1)) is not None:
        raise HTTPException(409, "Configuração inicial já concluída")
    if data.role != "admin":
        raise HTTPException(422, "O primeiro usuário deve ser administrador")
    user = add_user(data, db)
    audit(db, "user.bootstrap", user.id, user)
    db.commit()
    return user_data(user)


@router.post("/login")
def login(data: LoginInput, db: Db, request: Request):
    from sqlalchemy import text
    if db.bind.dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))
    else:
        db.execute(text("SELECT pg_advisory_xact_lock(73481294)"))
    now = datetime.now(timezone.utc)
    # Persistent limits survive restarts and apply across API processes.
    for value in ("user:" + data.username.lower(), "ip:" + (request.client.host if request.client else "unknown")):
        key = token_hash(value)
        attempt = db.get(LoginAttempt, key)
        if attempt is None:
            attempt = LoginAttempt(key=key, attempts=0, window_start=now)
            db.add(attempt)
        if utc(attempt.window_start) < now-timedelta(minutes=15):
            attempt.attempts, attempt.window_start = 0, now
        if attempt.attempts >= 20:
            raise HTTPException(429, "Muitas tentativas; aguarde 15 minutos", headers={"Retry-After": "900"})
        attempt.attempts += 1
    db.commit()
    user = db.scalar(select(User).where(User.username == data.username.lower()))
    # Perform the same expensive operation even for an unknown username.
    encoded = user.password_hash if user else hash_password("invalid-placeholder-password")
    valid = verify_password(data.password, encoded)
    if user is None or not user.active or not valid:
        raise HTTPException(401, "Usuário ou senha inválidos")
    token = secrets.token_urlsafe(32)
    expiry = datetime.now(timezone.utc) + timedelta(hours=8)
    db.add(LoginSession(token_hash=token_hash(token), user_id=user.id, expires_at=expiry))
    audit(db, "user.login", user.id, user)
    db.commit()
    return {"token": token, "expires_at": expiry.isoformat(), "user": user_data(user)}


@router.get("/me")
def me(actor: Actor):
    return user_data(actor)


@router.post("/logout", status_code=204)
def logout(actor: Actor, db: Db, authorization: Annotated[str, Header()]):
    db.delete(db.get(LoginSession, token_hash(authorization[7:])))
    audit(db, "user.logout", actor.id, actor)
    db.commit()


@router.get("/users", dependencies=[Depends(administrator)])
def users(db: Db):
    return [user_data(u) for u in db.scalars(select(User).order_by(User.name))]


@router.post("/users", status_code=201)
def create_user(data: UserInput, db: Db, actor: Annotated[User, Depends(administrator)]):
    user = add_user(data, db)
    audit(db, "user.create", user.id, actor)
    db.commit()
    return user_data(user)


class UserUpdate(BaseModel):
    active: bool | None = None
    password: str | None = Field(default=None, min_length=12, max_length=128)


@router.patch("/users/{user_id}")
def update_user(user_id: int, data: UserUpdate, db: Db, actor: Annotated[User, Depends(administrator)]):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Usuário não encontrado")
    if user.id == actor.id and data.active is False:
        raise HTTPException(409, "Você não pode desativar sua própria conta")
    if data.active is not None:
        user.active = data.active
    if data.password:
        user.password_hash = hash_password(data.password)
    if data.password or data.active is False:
        for session in db.scalars(select(LoginSession).where(LoginSession.user_id == user.id)):
            db.delete(session)
    audit(db, "user.update", user.id, actor)
    db.commit()
    return user_data(user)


@router.get("/audit", dependencies=[Depends(administrator)])
def events(db: Db):
    return [dict(id=e.id, actor_id=e.actor_id, action=e.action, entity_id=e.entity_id, created_at=e.created_at.isoformat())
            for e in db.scalars(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(200))]

import re
import secrets
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, text
from .auth import Actor, UserInput, add_user, administrator, audit, create_session, token_hash, utc
from .database import get_db
from .models import Barbershop, LoginAttempt, Professional, Service, WorkPeriod
from .schemas import normalize_phone
from sqlalchemy.orm import Session

router = APIRouter(tags=["Barbershops"])
Db = Annotated[Session, Depends(get_db)]


def shop_data(shop):
    return dict(id=shop.id, name=shop.name, slug=shop.slug, description=shop.description,
                city=shop.city, address=shop.address, phone=shop.phone, published=shop.published)


class ShopInput(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=500)
    city: str = Field(min_length=2, max_length=120)
    address: str = Field(min_length=2, max_length=200)
    phone: str

    @field_validator("name", "city", "address")
    @classmethod
    def require_text(cls, value):
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Informe pelo menos dois caracteres")
        return value

    @field_validator("phone")
    @classmethod
    def phone_with_ddd(cls, value):
        return normalize_phone(value)


class RegistrationInput(ShopInput):
    owner_name: str = Field(min_length=2, max_length=120)
    username: str = Field(min_length=3, max_length=120, pattern=r"^[a-zA-Z0-9_.@-]+$")
    password: str = Field(min_length=12, max_length=128)

    @field_validator("owner_name")
    @classmethod
    def owner_text(cls, value):
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Informe seu nome")
        return value


@router.get("/api/public/barbershops")
def directory(db: Db, q: str = Query(default="", max_length=120), offset: int = Query(default=0, ge=0)):
    query = select(Barbershop).where(Barbershop.published)
    if q.strip():
        term = f"%{q.strip()}%"
        query = query.where(Barbershop.name.ilike(term) | Barbershop.city.ilike(term))
    rows = list(db.scalars(query.order_by(Barbershop.name, Barbershop.id).offset(offset).limit(25)))
    return {"items": [shop_data(s) for s in rows[:24]], "has_more": len(rows) > 24}


@router.get("/api/public/barbershops/{shop_id}")
def public_shop(shop_id: int, db: Db):
    return shop_data(db.info["shop"])


@router.get("/api/public/barbershops/by-slug/{slug}")
def shop_by_slug(slug: str, db: Db):
    shop = db.scalar(select(Barbershop).where(Barbershop.slug == slug))
    if shop is None:
        raise HTTPException(404, "Código de barbearia não encontrado")
    return shop_data(shop)


@router.post("/api/public/barbershops", status_code=201)
def register(data: RegistrationInput, request: Request, db: Db):
    if db.bind.dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))
    else:
        db.execute(text("SELECT pg_advisory_xact_lock(73481295)"))
    now = datetime.now(timezone.utc)
    key = token_hash("shop-registration:" + (request.client.host if request.client else "unknown"))
    attempts = db.get(LoginAttempt, key)
    if attempts is None:
        attempts = LoginAttempt(key=key, attempts=0, window_start=now)
        db.add(attempts)
    if utc(attempts.window_start) < now-timedelta(hours=1):
        attempts.attempts, attempts.window_start = 0, now
    if attempts.attempts >= 5:
        raise HTTPException(429, "Limite de cadastros atingido; tente novamente em uma hora")
    attempts.attempts += 1
    slug = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", data.name).encode("ascii", "ignore").decode().lower()).strip("-") or "barbearia"
    shop = Barbershop(**data.model_dump(exclude={"owner_name", "username", "password"}), slug=slug+"-"+secrets.token_hex(4), published=False)
    db.add(shop)
    db.flush()
    db.info["shop_id"], db.info["shop"] = shop.id, shop
    owner = add_user(UserInput(username=data.username, name=data.owner_name, password=data.password, role="admin"), db)
    audit(db, "shop.register", shop.id, owner)
    session = create_session(db, owner)
    db.commit()
    return {**session, "shop": shop_data(shop)}


@router.get("/api/shops/{shop_id}/profile")
def profile(db: Db, actor: Actor):
    return shop_data(db.info["shop"])


class ProfileInput(ShopInput):
    published: bool


@router.put("/api/shops/{shop_id}/profile", dependencies=[Depends(administrator)])
def update_profile(data: ProfileInput, db: Db, actor: Actor):
    shop = db.scalar(select(Barbershop).where(Barbershop.id == actor.shop_id).with_for_update())
    if data.published:
        professional = db.scalar(select(Professional.id).where(Professional.active,
            Professional.services.any(Service.active), Professional.work_periods.any()).limit(1))
        if professional is None:
            raise HTTPException(409, "Cadastre um serviço ativo e um profissional com jornada antes de publicar")
    for field, value in data.model_dump().items():
        setattr(shop, field, value)
    audit(db, "shop.profile", shop.id, actor)
    db.commit()
    return shop_data(shop)

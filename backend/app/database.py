import os

from fastapi import HTTPException, Request
from sqlalchemy import ForeignKey, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker, with_loader_criteria


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./barberflow.db")
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class ShopScoped:
    shop_id: Mapped[int] = mapped_column(ForeignKey("barbershops.id"), nullable=False, default=1, index=True)


@event.listens_for(Session, "do_orm_execute")
def scope_shop_queries(state):
    shop_id = state.session.info.get("shop_id")
    if shop_id is not None and (state.is_select or state.is_update or state.is_delete):
        state.statement = state.statement.options(with_loader_criteria(
            ShopScoped, lambda model: model.shop_id == shop_id, include_aliases=True,
        ))


@event.listens_for(Session, "before_flush")
def scope_shop_writes(session, context, instances):
    shop_id = session.info.get("shop_id")
    if shop_id is None:
        return
    for row in session.new.union(session.dirty).union(session.deleted):
        if isinstance(row, ShopScoped):
            if row in session.new and row.shop_id is None:
                row.shop_id = shop_id
            if row.shop_id != shop_id:
                raise HTTPException(403, "Este registro pertence a outra barbearia")


def configure_shop_session(session, request):
    from .models import Barbershop
    value = request.path_params.get("shop_id")
    if value is not None:
        try:
            shop_id = int(value)
        except (TypeError, ValueError):
            raise HTTPException(404, "Barbearia não encontrada") from None
        shop = session.get(Barbershop, shop_id)
        if shop is None:
            raise HTTPException(404, "Barbearia não encontrada")
        session.info["shop_id"] = shop_id
        session.info["shop"] = shop


def get_db(request: Request):
    with SessionLocal() as session:
        configure_shop_session(session, request)
        yield session


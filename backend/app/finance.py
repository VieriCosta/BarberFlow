from datetime import date, datetime, timedelta, time, timezone
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo
import os

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from .database import get_db
from .auth import Actor, staff, administrator, audit
from .models import Appointment, CashClose, Expense, Payment, Professional

router = APIRouter(prefix="", tags=["Finance"], dependencies=[Depends(staff)])
Db = Annotated[Session, Depends(get_db)]
ZONE = ZoneInfo(os.getenv("BARBERFLOW_TIMEZONE", "America/Fortaleza"))
Method = Literal["cash", "pix", "credit", "debit"]


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def bounds(day):
    return (datetime.combine(day, time.min, ZONE).astimezone(timezone.utc),
            datetime.combine(day + timedelta(days=1), time.min, ZONE).astimezone(timezone.utc))


def money(value):
    return str(Decimal(value).quantize(Decimal("0.01")))


def lock_cash(db, day):
    if db.bind.dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))
    else:
        db.execute(text("SELECT pg_advisory_xact_lock(73481293)"))
    if db.scalar(select(CashClose.id).where(CashClose.day == day.isoformat())):
        raise HTTPException(409, "Caixa deste dia já fechado")


class PaymentInput(BaseModel):
    method: Method
    discount: Decimal = Field(default=0, ge=0, decimal_places=2)
    commission_percent: Decimal = Field(default=0, ge=0, le=100, decimal_places=2)


def payment_data(payment):
    return dict(id=payment.id, appointment_id=payment.appointment_id, amount=money(payment.amount),
                discount=money(payment.discount), commission=money(payment.commission), method=payment.method,
                paid_at=utc(payment.paid_at).astimezone(ZONE).isoformat())


@router.post("/appointments/{appointment_id}/payment", status_code=201)
def pay(appointment_id: int, data: PaymentInput, db: Db, actor: Actor):
    now = datetime.now(timezone.utc)
    lock_cash(db, now.astimezone(ZONE).date())
    appointment = db.scalar(select(Appointment).where(Appointment.id == appointment_id).with_for_update())
    if appointment is None:
        raise HTTPException(404, "Agendamento não encontrado")
    if appointment.status != "completed":
        raise HTTPException(409, "Conclua o atendimento antes de registrar o pagamento")
    if db.scalar(select(Payment.id).where(Payment.appointment_id == appointment_id)):
        raise HTTPException(409, "Pagamento já registrado")
    if data.discount > appointment.price:
        raise HTTPException(422, "Desconto maior que o valor do atendimento")
    amount = appointment.price - data.discount
    commission = (amount * data.commission_percent / 100).quantize(Decimal("0.01"))
    payment = Payment(appointment_id=appointment_id, amount=amount, discount=data.discount, method=data.method,
                      commission=commission, paid_at=now, actor_id=actor.id)
    db.add(payment)
    audit(db, "payment.create", appointment_id, actor)
    db.commit()
    return payment_data(payment)


class ExpenseInput(BaseModel):
    description: str = Field(min_length=2, max_length=200)
    amount: Decimal = Field(gt=0, decimal_places=2)
    method: Method


@router.post("/finance/expenses", status_code=201)
def expense(data: ExpenseInput, db: Db, actor: Actor):
    now = datetime.now(timezone.utc)
    lock_cash(db, now.astimezone(ZONE).date())
    row = Expense(**data.model_dump(), actor_id=actor.id, paid_at=now)
    db.add(row)
    db.flush()
    audit(db, "expense.create", row.id, actor)
    db.commit()
    return {"id": row.id}


def summary(db, day):
    start, end = bounds(day)
    payments = list(db.scalars(select(Payment).where(Payment.paid_at >= start, Payment.paid_at < end)))
    expenses = list(db.scalars(select(Expense).where(Expense.paid_at >= start, Expense.paid_at < end)))
    received = sum((p.amount for p in payments), Decimal(0))
    spent = sum((e.amount for e in expenses), Decimal(0))
    commissions = sum((p.commission for p in payments), Decimal(0))
    cash = sum((p.amount for p in payments if p.method == "cash"), Decimal(0)) - sum((e.amount for e in expenses if e.method == "cash"), Decimal(0))
    close = db.scalar(select(CashClose).where(CashClose.day == day.isoformat()))
    pending = list(db.scalars(select(Appointment).where(Appointment.status == "completed",
                  Appointment.starts_at >= start, Appointment.starts_at < end,
                  ~Appointment.id.in_(select(Payment.appointment_id)))))
    return dict(day=day.isoformat(), received=money(received), expenses_total=money(spent), commissions=money(commissions),
                balance=money(received-spent), after_commissions=money(received-spent-commissions), cash_expected=money(cash),
                by_method={method: money(sum((p.amount for p in payments if p.method == method), Decimal(0)))
                           for method in ("cash", "pix", "credit", "debit")},
                payments=[payment_data(p) for p in payments],
                expenses=[dict(id=e.id, description=e.description, amount=money(e.amount), method=e.method) for e in expenses],
                pending=[dict(id=a.id, customer_name=a.customer_name, service_name=a.service_name, price=money(a.price)) for a in pending],
                pending_total=money(sum((a.price for a in pending), Decimal(0))),
                close=None if close is None else dict(id=close.id, counted=money(close.cash_counted),
                      expected=money(close.cash_expected), difference=money(close.cash_counted-close.cash_expected), notes=close.notes))


@router.get("/finance/daily")
def daily(db: Db, day: date = Query(default_factory=lambda: datetime.now(ZONE).date())):
    return summary(db, day)


class CloseInput(BaseModel):
    day: date
    cash_counted: Decimal = Field(ge=0, decimal_places=2)
    notes: str = Field(default="", max_length=1000)


@router.post("/finance/close", status_code=201)
def close_cash(data: CloseInput, db: Db, actor: Annotated[object, Depends(administrator)]):
    if data.day > datetime.now(ZONE).date():
        raise HTTPException(422, "Não é possível fechar um caixa futuro")
    lock_cash(db, data.day)
    totals = summary(db, data.day)
    db.add(CashClose(day=data.day.isoformat(), received=Decimal(totals["received"]), expenses=Decimal(totals["expenses_total"]),
                    cash_expected=Decimal(totals["cash_expected"]), cash_counted=data.cash_counted, notes=data.notes,
                    actor_id=actor.id, closed_at=datetime.now(timezone.utc)))
    audit(db, "cash.close", actor=actor)
    db.commit()
    return summary(db, data.day)


@router.get("/dashboard")
def dashboard(db: Db, day: date = Query(default_factory=lambda: datetime.now(ZONE).date())):
    from .schedule import day_periods
    start, end = bounds(day)
    appointments = list(db.scalars(select(Appointment).where(Appointment.starts_at >= start, Appointment.starts_at < end)))
    professionals = list(db.scalars(select(Professional).where(Professional.active)))
    occupation = []
    for professional in professionals:
        capacity = sum((b.hour*60+b.minute)-(a.hour*60+a.minute) for a,b in day_periods(db, professional, day))
        attended = [a for a in appointments if a.professional_id == professional.id and a.status in ("scheduled", "in_progress", "completed")]
        minutes = sum((utc(a.ends_at)-utc(a.starts_at)).total_seconds()/60 for a in attended)
        occupation.append(dict(professional_id=professional.id, name=professional.name, appointments=len(attended),
                               available_minutes=capacity, booked_minutes=minutes,
                               occupancy_percent=round(minutes/capacity*100, 1) if capacity else 0))
    return {**summary(db, day), "appointments_count": len(appointments),
            "completed_count": sum(a.status == "completed" for a in appointments),
            "no_shows_count": sum(a.status == "no_show" for a in appointments), "occupation": occupation}

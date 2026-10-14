import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from .auth import token_hash, audit
from .database import get_db
from .models import Appointment, BookingAccess

router = APIRouter(prefix="/api/public/reservation", tags=["Customer portal"])
Db = Annotated[Session, Depends(get_db)]


def issue_access(db, appointment):
    token = secrets.token_urlsafe(32)
    db.add(BookingAccess(token_hash=token_hash(token), appointment_id=appointment.id))
    return token


def access(db, authorization, lock=False):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(404, "Link de reserva inválido")
    grant = db.get(BookingAccess, token_hash(authorization[7:]))
    if grant is None:
        raise HTTPException(404, "Link de reserva inválido")
    query = select(Appointment).where(Appointment.id == grant.appointment_id)
    appointment = db.scalar(query.with_for_update() if lock else query)
    if appointment is None:
        raise HTTPException(404, "Reserva não encontrada")
    return appointment


def ensure_editable(appointment):
    from .booking import as_utc
    minimum = int(os.getenv("BARBERFLOW_CUSTOMER_CHANGE_HOURS", "2"))
    if appointment.status != "scheduled" or as_utc(appointment.starts_at) <= datetime.now(timezone.utc)+timedelta(hours=minimum):
        raise HTTPException(409, f"Alterações permitidas até {minimum} hora(s) antes do atendimento; entre em contato com a barbearia")


@router.get("")
def reservation(db: Db, authorization: Annotated[str | None, Header()] = None):
    from .booking import appointment_data
    appointment = access(db, authorization)
    return {**appointment_data(appointment), "change_hours": int(os.getenv("BARBERFLOW_CUSTOMER_CHANGE_HOURS", "2"))}


@router.post("/cancel")
def cancel(db: Db, authorization: Annotated[str | None, Header()] = None):
    from .booking import begin_write, appointment_data
    from .notifications import cancel_pending
    begin_write(db)
    appointment = access(db, authorization, lock=True)
    ensure_editable(appointment)
    appointment.status = "cancelled"
    cancel_pending(db, appointment.id)
    audit(db, "customer.cancel", appointment.id)
    db.commit()
    return appointment_data(appointment)


from .booking import RescheduleInput


@router.post("/reschedule")
def reschedule(data: RescheduleInput, db: Db, authorization: Annotated[str | None, Header()] = None):
    # Use the same lock ordering and validations as an internal reschedule.
    from .booking import reschedule_appointment
    from .models import User
    appointment = access(db, authorization)
    ensure_editable(appointment)
    appointment_id = appointment.id
    db.rollback()
    # Authorization is the single-appointment access grant, never a user-provided id.
    return reschedule_appointment(appointment_id, data, db, User(role="reception"), customer=True)

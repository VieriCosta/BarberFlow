"""Durable outbox. Delivery is performed by `python -m app.worker`, never in requests."""
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from .auth import administrator, Actor, audit, utc
from .database import get_db
from .models import Appointment, Notification

router = APIRouter(prefix="/api/notifications", tags=["Notifications"], dependencies=[Depends(administrator)])
Db = Annotated[Session, Depends(get_db)]


def queue(db, appointment, kind="confirmation"):
    now = datetime.now(timezone.utc)
    for name, due in [(kind, now), ("reminder", max(now, utc(appointment.starts_at)-timedelta(hours=24)))]:
        row = db.scalar(select(Notification).where(Notification.appointment_id == appointment.id, Notification.kind == name))
        if row is None:
            row = Notification(appointment_id=appointment.id, kind=name)
            db.add(row)
        row.due_at, row.state, row.attempts, row.last_error, row.sent_at, row.locked_at = due, "pending", 0, "", None, None
        row.generation = secrets.token_hex(16)


def cancel_pending(db, appointment_id):
    for row in db.scalars(select(Notification).where(Notification.appointment_id == appointment_id, Notification.state.in_(["pending", "failed"]))):
        row.state = "cancelled"


@router.get("")
def notifications(db: Db):
    rows = db.scalars(select(Notification).order_by(Notification.id.desc()).limit(200))
    return {"configured": bool(os.getenv("BARBERFLOW_NOTIFICATION_WEBHOOK") or os.getenv("BARBERFLOW_SMTP_HOST")),
            "items": [dict(id=n.id, appointment_id=n.appointment_id, kind=n.kind, state=n.state,
                       attempts=n.attempts, last_error=n.last_error, due_at=n.due_at.isoformat()) for n in rows]}


@router.post("/{notification_id}/retry")
def retry(notification_id: int, db: Db, actor: Actor):
    row = db.scalar(select(Notification).where(Notification.id == notification_id).with_for_update())
    if row is None:
        raise HTTPException(404, "Notificação não encontrada")
    appointment = db.get(Appointment, row.appointment_id)
    if appointment.status != "scheduled" or row.state != "failed":
        raise HTTPException(409, "Somente falhas de reservas pendentes podem ser reenviadas")
    row.state, row.attempts, row.due_at, row.last_error = "pending", 0, datetime.now(timezone.utc), ""
    audit(db, "notification.retry", row.id, actor)
    db.commit()
    return {"status": "pending"}

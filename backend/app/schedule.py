import json
from datetime import date, datetime, time, timezone
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from .auth import Actor, administrator, audit
from .database import get_db
from .models import Appointment, Professional, ScheduleException

router = APIRouter(prefix="/schedule-exceptions", tags=["Schedule"], dependencies=[Depends(administrator)])
Db = Annotated[Session, Depends(get_db)]


def day_periods(db, professional, day):
    exception = db.scalar(select(ScheduleException).where(ScheduleException.professional_id == professional.id,
                                                          ScheduleException.day == day.isoformat()))
    if exception:
        return [(time.fromisoformat(p["starts_at"]), time.fromisoformat(p["ends_at"])) for p in json.loads(exception.periods_json)]
    return [(p.starts_at, p.ends_at) for p in professional.work_periods if p.weekday == day.weekday()]


class ExceptionPeriod(BaseModel):
    starts_at: time
    ends_at: time


class ExceptionInput(BaseModel):
    professional_id: int
    day: date
    reason: str = Field(default="", max_length=200)
    periods: list[ExceptionPeriod] = Field(default_factory=list, max_length=10)


def exception_data(row):
    return dict(id=row.id, professional_id=row.professional_id, day=row.day, reason=row.reason, periods=json.loads(row.periods_json))


@router.get("")
def exceptions(db: Db):
    return [exception_data(e) for e in db.scalars(select(ScheduleException).order_by(ScheduleException.day.desc()).limit(500))]


@router.put("")
def save_exception(data: ExceptionInput, db: Db, actor: Actor):
    from .booking import ZONE, as_utc
    if db.bind.dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))
    professional = db.scalar(select(Professional).where(Professional.id == data.professional_id).with_for_update())
    if professional is None:
        raise HTTPException(404, "Profissional não encontrado")
    periods = sorted(data.periods, key=lambda p: p.starts_at)
    if any(p.starts_at >= p.ends_at for p in periods) or any(a.ends_at > b.starts_at for a,b in zip(periods, periods[1:])):
        raise HTTPException(422, "Períodos inválidos ou sobrepostos")
    for appointment in db.scalars(select(Appointment).where(Appointment.professional_id == professional.id,
                              Appointment.status.in_(["scheduled", "in_progress"]), Appointment.ends_at > datetime.now(timezone.utc))):
        start, end = as_utc(appointment.starts_at).astimezone(ZONE), as_utc(appointment.ends_at).astimezone(ZONE)
        if start.date() == data.day and not any(p.starts_at <= start.time().replace(tzinfo=None) and end.time().replace(tzinfo=None) <= p.ends_at for p in periods):
            raise HTTPException(409, "Reagende os atendimentos antes de alterar o expediente deste dia")
    row = db.scalar(select(ScheduleException).where(ScheduleException.professional_id == professional.id, ScheduleException.day == data.day.isoformat()))
    if row is None:
        row = ScheduleException(professional_id=professional.id, day=data.day.isoformat())
        db.add(row)
    row.reason = data.reason
    row.periods_json = json.dumps([p.model_dump(mode="json") for p in periods])
    db.flush()
    audit(db, "schedule.exception.save", row.id, actor)
    db.commit()
    return exception_data(row)


@router.delete("/{exception_id}", status_code=204)
def delete_exception(exception_id: int, db: Db, actor: Actor):
    from .booking import ZONE, as_utc
    if db.bind.dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))
    row = db.get(ScheduleException, exception_id)
    if row is None:
        raise HTTPException(404, "Exceção não encontrada")
    professional = db.scalar(select(Professional).where(Professional.id == row.professional_id).with_for_update())
    for a in db.scalars(select(Appointment).where(Appointment.professional_id == row.professional_id,
                       Appointment.status.in_(["scheduled", "in_progress"]), Appointment.ends_at > datetime.now(timezone.utc))):
        start, end = as_utc(a.starts_at).astimezone(ZONE), as_utc(a.ends_at).astimezone(ZONE)
        if start.date().isoformat() == row.day and not any(p.weekday == start.weekday() and p.starts_at <= start.time().replace(tzinfo=None) and end.time().replace(tzinfo=None) <= p.ends_at for p in professional.work_periods):
            raise HTTPException(409, "A jornada regular não comporta os agendamentos deste dia")
    audit(db, "schedule.exception.delete", row.id, actor)
    db.delete(row)
    db.commit()

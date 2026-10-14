import os
import re
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select, text
from sqlalchemy.orm import Session, selectinload

from .database import get_db
from .models import Appointment, Customer, Professional, ScheduleBlock, Service, WorkPeriod
from .auth import Actor, professional_scope, audit


ZONE = ZoneInfo(os.getenv("BARBERFLOW_TIMEZONE", "America/Fortaleza"))
MAX_DAYS_AHEAD = int(os.getenv("BARBERFLOW_MAX_DAYS_AHEAD", "60"))
MIN_MINUTES_AHEAD = int(os.getenv("BARBERFLOW_MIN_MINUTES_AHEAD", "0"))
BUSY_STATUSES = ("scheduled", "in_progress", "completed")
OPEN_STATUSES = ("scheduled", "in_progress")


Db = Annotated[Session, Depends(get_db)]


from .schemas import ServiceInput, ServiceUpdate, ProfessionalInput, ProfessionalUpdate, CustomerInput, CustomerUpdate, PeriodInput, BookingInput, RescheduleInput, StatusInput, BlockInput

app = APIRouter(tags=["Bookings and catalog"])

def service_data(service: Service) -> dict:
    return {"id": service.id, "name": service.name, "description": service.description,
            "price": str(service.price), "duration_minutes": service.duration_minutes, "active": service.active}


def professional_data(professional: Professional) -> dict:
    return {"id": professional.id, "name": professional.name, "active": professional.active,
            "service_ids": sorted(service.id for service in professional.services),
            "work_periods": [{"weekday": period.weekday, "starts_at": period.starts_at.isoformat(timespec="minutes"),
                              "ends_at": period.ends_at.isoformat(timespec="minutes")}
                             for period in sorted(professional.work_periods, key=lambda p: (p.weekday, p.starts_at))]}


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def appointment_data(appointment: Appointment) -> dict:
    # SQLite does not preserve the tzinfo flag; all stored datetimes are UTC.
    start = as_utc(appointment.starts_at)
    end = as_utc(appointment.ends_at)
    return {"id": appointment.id, "service_id": appointment.service_id,
            "service_name": appointment.service_name, "professional_id": appointment.professional_id,
            "professional_name": appointment.professional.name, "customer_name": appointment.customer_name,
            "customer_phone": appointment.customer_phone, "starts_at": start.astimezone(ZONE).isoformat(),
            "ends_at": end.astimezone(ZONE).isoformat(), "customer_id": appointment.customer_id, "price": str(appointment.price),
            "status": appointment.status, "paid": appointment.payment is not None}


def block_data(block: ScheduleBlock) -> dict:
    return {"id": block.id, "professional_id": block.professional_id,
            "professional_name": block.professional.name,
            "starts_at": as_utc(block.starts_at).astimezone(ZONE).isoformat(),
            "ends_at": as_utc(block.ends_at).astimezone(ZONE).isoformat(),
            "reason": block.reason}


def customer_data(db: Session, customer: Customer) -> dict:
    total = db.scalar(select(func.count(Appointment.id)).where(Appointment.customer_id == customer.id)) or 0
    missed = db.scalar(select(func.count(Appointment.id)).where(
        Appointment.customer_id == customer.id, Appointment.status == "no_show")) or 0
    return {"id": customer.id, "name": customer.name, "phone": customer.phone,
            "email": customer.email, "notes": customer.notes,
            "appointments_count": total, "no_shows_count": missed}


def begin_write(db: Session) -> None:
    if db.bind.dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))


def has_future_booking(db: Session, *conditions) -> bool:
    return db.scalar(select(Appointment.id).where(
        Appointment.status.in_(OPEN_STATUSES),
        Appointment.starts_at >= datetime.now(timezone.utc),
        *conditions,
    ).limit(1)) is not None


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/public/config")
def public_config():
    return {"timezone": ZONE.key}


@app.get("/api/public/services")
def public_services(db: Db):
    return [service_data(s) for s in db.scalars(select(Service).where(Service.active).order_by(Service.name))]


@app.get("/api/public/professionals")
def public_professionals(db: Db, service_id: int | None = None):
    query = select(Professional).options(selectinload(Professional.services), selectinload(Professional.work_periods)).where(Professional.active)
    if service_id is not None:
        query = query.where(Professional.services.any(and_(Service.id == service_id, Service.active)))
    return [professional_data(p) for p in db.scalars(query.order_by(Professional.name))]


def validate_booking_time(start: datetime, duration: int) -> tuple[datetime, datetime]:
    start = start.astimezone(ZONE)
    now = datetime.now(ZONE)
    if start < now + timedelta(minutes=MIN_MINUTES_AHEAD):
        raise HTTPException(422, "Não é possível agendar no passado ou antes da antecedência mínima")
    if start.date() > (now + timedelta(days=MAX_DAYS_AHEAD)).date():
        raise HTTPException(422, "Data além do limite de agendamento")
    if start.minute % 15 or start.second or start.microsecond:
        raise HTTPException(422, "Escolha um horário em intervalos de 15 minutos")
    return start, start + timedelta(minutes=duration)


def is_available(db: Session, professional: Professional, start: datetime, end: datetime,
                 exclude_appointment_id: int | None = None) -> bool:
    if not professional.active or start.date() != end.date():
        return False
    local_start = start.time().replace(tzinfo=None)
    local_end = end.time().replace(tzinfo=None)
    from .schedule import day_periods
    if not any(a <= local_start and local_end <= b for a, b in day_periods(db, professional, start.date())):
        return False
    start_utc = start.astimezone(timezone.utc)
    end_utc = end.astimezone(timezone.utc)
    query = select(Appointment.id).where(
        Appointment.professional_id == professional.id,
        Appointment.status.in_(BUSY_STATUSES),
        Appointment.starts_at < end_utc,
        Appointment.ends_at > start_utc,
    )
    if exclude_appointment_id is not None:
        query = query.where(Appointment.id != exclude_appointment_id)
    if db.scalar(query.limit(1)) is not None:
        return False
    return db.scalar(select(ScheduleBlock.id).where(
        ScheduleBlock.professional_id == professional.id,
        ScheduleBlock.starts_at < end_utc,
        ScheduleBlock.ends_at > start_utc,
    ).limit(1)) is None


def remember_customer(db: Session, name: str, phone: str) -> int:
    values = {"name": name, "phone": phone, "notes": ""}
    dialect = db.bind.dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
        statement = insert(Customer).values(**values).on_conflict_do_nothing(index_elements=[Customer.phone])
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
        statement = insert(Customer).values(**values).on_conflict_do_nothing(index_elements=[Customer.phone])
    else:
        if db.scalar(select(Customer.id).where(Customer.phone == phone)) is None:
            db.add(Customer(**values))
        db.flush()
        return db.scalar(select(Customer.id).where(Customer.phone == phone))
    db.execute(statement)
    return db.scalar(select(Customer.id).where(Customer.phone == phone))


@app.get("/api/public/availability")
def availability(db: Db, service_id: int, day: date, professional_id: int | None = None):
    service = db.get(Service, service_id)
    if service is None or not service.active:
        raise HTTPException(404, "Serviço não encontrado")
    query = select(Professional).options(selectinload(Professional.services), selectinload(Professional.work_periods)).where(Professional.active, Professional.services.any(Service.id == service_id))
    if professional_id:
        query = query.where(Professional.id == professional_id)
    professionals = list(db.scalars(query.order_by(Professional.id)))
    if professional_id and not professionals:
        raise HTTPException(404, "Profissional não encontrado para este serviço")
    slots = []
    start = datetime.combine(day, time.min, tzinfo=ZONE)
    for offset in range(0, 24 * 60, 15):
        candidate = start + timedelta(minutes=offset)
        try:
            candidate, end = validate_booking_time(candidate, service.duration_minutes)
        except HTTPException:
            continue
        for professional in professionals:
            if is_available(db, professional, candidate, end):
                slots.append({"starts_at": candidate.isoformat(), "professional_id": professional.id,
                              "professional_name": professional.name})
    return slots


def reserve(data: BookingInput, db: Session, actor=None) -> dict:
    # SQLite serializes writers; PostgreSQL locks each professional row while checking overlap.
    begin_write(db)
    service = db.scalar(select(Service).where(Service.id == data.service_id).with_for_update())
    if service is None or not service.active:
        raise HTTPException(404, "Serviço não encontrado")
    start, end = validate_booking_time(data.starts_at, service.duration_minutes)
    query = select(Professional).options(selectinload(Professional.services), selectinload(Professional.work_periods)).where(
        Professional.active, Professional.services.any(Service.id == service.id))
    if data.professional_id is not None:
        query = query.where(Professional.id == data.professional_id)
    professional_ids = list(db.scalars(query.with_only_columns(Professional.id).order_by(Professional.id)))
    for professional_id in professional_ids:
        locked = db.scalar(select(Professional).where(Professional.id == professional_id).with_for_update())
        db.refresh(locked, attribute_names=["work_periods"])
        if is_available(db, locked, start, end):
            appointment = Appointment(service_id=service.id, professional_id=locked.id,
                                      customer_name=data.customer_name.strip(), customer_phone=data.customer_phone,
                                      starts_at=start.astimezone(timezone.utc), ends_at=end.astimezone(timezone.utc),
                                      price=service.price, service_name=service.name)
            db.add(appointment)
            appointment.customer_id = remember_customer(db, data.customer_name.strip(), data.customer_phone)
            db.flush()
            audit(db, "appointment.create", appointment.id, actor)
            from .customer_portal import issue_access
            from .notifications import queue
            token = issue_access(db, appointment)
            if data.customer_email:
                customer = db.get(Customer, appointment.customer_id)
                if not customer.email:
                    customer.email = data.customer_email
            queue(db, appointment)
            db.commit()
            db.refresh(appointment)
            return {**appointment_data(appointment), "manage_token": token}
    raise HTTPException(409, "Horário indisponível; escolha outro horário")


@app.post("/api/public/appointments", status_code=201)
def create_public_appointment(data: BookingInput, db: Db):
    return reserve(data, db)


@app.post("/api/appointments", status_code=201)
def create_internal_appointment(data: BookingInput, db: Db, actor: Actor):
    professional_scope(actor, data.professional_id)
    if actor.role == "barber":
        data.professional_id = actor.professional_id
    return reserve(data, db, actor)


@app.get("/api/appointments")
def list_appointments(db: Db, day: date = Query(default_factory=lambda: datetime.now(ZONE).date()),
                      view: Literal["day", "week"] = "day", professional_id: int | None = None, *, actor: Actor):
    professional_id = professional_scope(actor, professional_id)
    start, end = agenda_range(day, view)
    query = select(Appointment).options(selectinload(Appointment.professional), selectinload(Appointment.payment)).where(
        and_(Appointment.starts_at >= start, Appointment.starts_at < end)).order_by(Appointment.starts_at)
    if professional_id is not None:
        query = query.where(Appointment.professional_id == professional_id)
    return [appointment_data(a) for a in db.scalars(query)]


def agenda_range(day: date, view: Literal["day", "week"]) -> tuple[datetime, datetime]:
    first = day - timedelta(days=day.weekday()) if view == "week" else day
    after = first + timedelta(days=7 if view == "week" else 1)
    return (datetime.combine(first, time.min, tzinfo=ZONE).astimezone(timezone.utc),
            datetime.combine(after, time.min, tzinfo=ZONE).astimezone(timezone.utc))


@app.get("/api/blocks")
def list_blocks(db: Db, day: date = Query(default_factory=lambda: datetime.now(ZONE).date()),
                view: Literal["day", "week"] = "day", professional_id: int | None = None, *, actor: Actor):
    professional_id = professional_scope(actor, professional_id)
    start, end = agenda_range(day, view)
    query = select(ScheduleBlock).options(selectinload(ScheduleBlock.professional)).where(
        ScheduleBlock.starts_at < end, ScheduleBlock.ends_at > start).order_by(ScheduleBlock.starts_at)
    if professional_id is not None:
        query = query.where(ScheduleBlock.professional_id == professional_id)
    return [block_data(block) for block in db.scalars(query)]


@app.get("/api/agenda-hours")
def agenda_hours(db: Db, actor: Actor, day: date, view: Literal["day", "week"] = "day", professional_id: int | None = None):
    from .schedule import day_periods
    from .models import ScheduleException
    professional_id = professional_scope(actor, professional_id)
    query = select(Professional).where(Professional.active)
    if professional_id is not None:
        query = query.where(Professional.id == professional_id)
    professionals = list(db.scalars(query))
    first = day-timedelta(days=day.weekday()) if view == "week" else day
    results = []
    for offset in range(7 if view == "week" else 1):
        current = first+timedelta(days=offset)
        for professional in professionals:
            exception = db.scalar(select(ScheduleException).where(ScheduleException.professional_id == professional.id,
                                                                   ScheduleException.day == current.isoformat()))
            results.append(dict(professional_id=professional.id, day=current.isoformat(), reason=exception.reason if exception else "",
                periods=[dict(starts_at=a.isoformat(timespec="minutes"), ends_at=b.isoformat(timespec="minutes"))
                         for a,b in day_periods(db, professional, current)]))
    return results


@app.post("/api/blocks", status_code=201)
def create_block(data: BlockInput, db: Db, actor: Actor):
    professional_scope(actor, data.professional_id)
    start, end = data.starts_at.astimezone(timezone.utc), data.ends_at.astimezone(timezone.utc)
    if end <= start or start < datetime.now(timezone.utc):
        raise HTTPException(422, "Informe um intervalo futuro com fim após o início")
    begin_write(db)
    professional = db.scalar(select(Professional).where(Professional.id == data.professional_id).with_for_update())
    if professional is None or not professional.active:
        raise HTTPException(404, "Profissional ativo não encontrado")
    appointment_conflict = db.scalar(select(Appointment.id).where(
        Appointment.professional_id == professional.id, Appointment.status.in_(BUSY_STATUSES),
        Appointment.starts_at < end, Appointment.ends_at > start).limit(1))
    block_conflict = db.scalar(select(ScheduleBlock.id).where(
        ScheduleBlock.professional_id == professional.id, ScheduleBlock.starts_at < end,
        ScheduleBlock.ends_at > start).limit(1))
    if appointment_conflict is not None or block_conflict is not None:
        raise HTTPException(409, "O intervalo já possui atendimento ou bloqueio")
    block = ScheduleBlock(professional_id=professional.id, starts_at=start, ends_at=end,
                          reason=data.reason.strip())
    db.add(block)
    db.flush()
    audit(db, "block.create", block.id, actor)
    db.commit()
    db.refresh(block)
    return block_data(block)


@app.delete("/api/blocks/{block_id}", status_code=204)
def delete_block(block_id: int, db: Db, actor: Actor):
    begin_write(db)
    block = db.get(ScheduleBlock, block_id)
    if block is None:
        raise HTTPException(404, "Bloqueio não encontrado")
    professional_scope(actor, block.professional_id)
    audit(db, "block.delete", block.id, actor)
    db.delete(block)
    db.commit()


@app.post("/api/appointments/{appointment_id}/reschedule")
def reschedule_appointment(appointment_id: int, data: RescheduleInput, db: Db, actor: Actor):
    return reschedule_booking(appointment_id, data, db, actor=actor)


def reschedule_booking(appointment_id: int, data: RescheduleInput, db: Session, actor=None, customer=False):
    if actor:
        professional_scope(actor, data.professional_id)
    begin_write(db)
    professional = db.scalar(select(Professional).options(selectinload(Professional.services),
        selectinload(Professional.work_periods)).where(Professional.id == data.professional_id).with_for_update())
    if professional is None or not professional.active:
        raise HTTPException(404, "Profissional ativo não encontrado")
    appointment = db.scalar(select(Appointment).where(Appointment.id == appointment_id)
                            .with_for_update().execution_options(populate_existing=True))
    if appointment is None:
        raise HTTPException(404, "Agendamento não encontrado")
    if actor:
        professional_scope(actor, appointment.professional_id)
    if customer:
        from .customer_portal import ensure_editable
        ensure_editable(appointment)
    if appointment.status != "scheduled":
        raise HTTPException(409, "Somente agendamentos pendentes podem ser reagendados")
    service = db.get(Service, appointment.service_id)
    if service is None or not service.active or service not in professional.services:
        raise HTTPException(422, "Profissional não atende este serviço ativo")
    duration = int((as_utc(appointment.ends_at) - as_utc(appointment.starts_at)).total_seconds() / 60)
    start, end = validate_booking_time(data.starts_at, duration)
    if not is_available(db, professional, start, end, exclude_appointment_id=appointment.id):
        raise HTTPException(409, "Horário indisponível; escolha outro horário")
    audit(db, "customer.reschedule" if customer else "appointment.reschedule", appointment.id, actor)
    appointment.professional_id = professional.id
    appointment.starts_at = start.astimezone(timezone.utc)
    appointment.ends_at = end.astimezone(timezone.utc)
    from .notifications import queue, cancel_pending
    cancel_pending(db, appointment.id)
    queue(db, appointment, "rescheduled")
    db.commit()
    db.refresh(appointment)
    return appointment_data(appointment)


@app.patch("/api/appointments/{appointment_id}/status")
def update_appointment_status(appointment_id: int, data: StatusInput, db: Db, actor: Actor):
    begin_write(db)
    appointment = db.scalar(select(Appointment).where(Appointment.id == appointment_id).with_for_update())
    if appointment is None:
        raise HTTPException(404, "Agendamento não encontrado")
    professional_scope(actor, appointment.professional_id)
    allowed = {"scheduled": {"in_progress", "cancelled", "no_show"},
               "in_progress": {"completed", "cancelled"}}
    if data.status not in allowed.get(appointment.status, set()):
        raise HTTPException(409, "Mudança de status não permitida")
    if data.status == "no_show" and as_utc(appointment.starts_at) > datetime.now(timezone.utc):
        raise HTTPException(409, "A falta só pode ser registrada após o horário marcado")
    audit(db, "appointment.status." + data.status, appointment.id, actor)
    appointment.status = data.status
    from .notifications import cancel_pending
    cancel_pending(db, appointment.id)
    db.commit()
    db.refresh(appointment)
    return appointment_data(appointment)

import os
import re
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .database import Base, engine, get_db
from .models import Appointment, Customer, Professional, ScheduleBlock, Service, WorkPeriod


ZONE = ZoneInfo(os.getenv("BARBERFLOW_TIMEZONE", "America/Fortaleza"))
MAX_DAYS_AHEAD = int(os.getenv("BARBERFLOW_MAX_DAYS_AHEAD", "60"))
MIN_MINUTES_AHEAD = int(os.getenv("BARBERFLOW_MIN_MINUTES_AHEAD", "0"))
BUSY_STATUSES = ("scheduled", "in_progress", "completed")
OPEN_STATUSES = ("scheduled", "in_progress")


Db = Annotated[Session, Depends(get_db)]


class ServiceInput(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=500)
    price: Decimal = Field(ge=0, decimal_places=2)
    duration_minutes: int = Field(gt=0, le=480)


class ServiceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    price: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    duration_minutes: int | None = Field(default=None, gt=0, le=480)
    active: bool | None = None


class ProfessionalInput(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    service_ids: list[int] = Field(min_length=1)


class ProfessionalUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    service_ids: list[int] | None = Field(default=None, min_length=1)
    active: bool | None = None


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if len(digits) not in (10, 11):
        raise ValueError("Informe um telefone brasileiro com DDD")
    return digits


class CustomerInput(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    phone: str
    email: str | None = Field(default=None, max_length=255, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    notes: str = Field(default="", max_length=1000)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        return normalize_phone(value)


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    phone: str | None = None
    email: str | None = Field(default=None, max_length=255, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str | None) -> str | None:
        return normalize_phone(value) if value is not None else None


class PeriodInput(BaseModel):
    weekday: int = Field(ge=0, le=6)
    starts_at: time
    ends_at: time


class BookingInput(BaseModel):
    service_id: int
    professional_id: int | None = None
    starts_at: datetime
    customer_name: str = Field(min_length=2, max_length=120)
    customer_phone: str

    @field_validator("customer_phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        return normalize_phone(value)

    @field_validator("starts_at")
    @classmethod
    def require_offset(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Informe data e hora com fuso horário")
        return value


class RescheduleInput(BaseModel):
    starts_at: datetime
    professional_id: int

    @field_validator("starts_at")
    @classmethod
    def require_offset(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Informe data e hora com fuso horário")
        return value


class StatusInput(BaseModel):
    status: Literal["in_progress", "completed", "cancelled", "no_show"]


class BlockInput(BaseModel):
    professional_id: int
    starts_at: datetime
    ends_at: datetime
    reason: str = Field(default="", max_length=200)

    @field_validator("starts_at", "ends_at")
    @classmethod
    def require_offset(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Informe data e hora com fuso horário")
        return value


app = FastAPI(title="BarberFlow API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("BARBERFLOW_CORS_ORIGINS", "http://localhost:4200").split(","),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)


@app.on_event("startup")
def initialize_database():
    Base.metadata.create_all(bind=engine)


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
            "ends_at": end.astimezone(ZONE).isoformat(), "price": str(appointment.price), "status": appointment.status}


def block_data(block: ScheduleBlock) -> dict:
    return {"id": block.id, "professional_id": block.professional_id,
            "professional_name": block.professional.name,
            "starts_at": as_utc(block.starts_at).astimezone(ZONE).isoformat(),
            "ends_at": as_utc(block.ends_at).astimezone(ZONE).isoformat(),
            "reason": block.reason}


def customer_data(db: Session, customer: Customer) -> dict:
    total = db.scalar(select(func.count(Appointment.id)).where(Appointment.customer_phone == customer.phone)) or 0
    missed = db.scalar(select(func.count(Appointment.id)).where(
        Appointment.customer_phone == customer.phone, Appointment.status == "no_show")) or 0
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


@app.get("/api/services")
def list_services(db: Db):
    return [service_data(s) for s in db.scalars(select(Service).order_by(Service.id))]


@app.post("/api/services", status_code=201)
def create_service(data: ServiceInput, db: Db):
    service = Service(**data.model_dump())
    db.add(service)
    db.commit()
    db.refresh(service)
    return service_data(service)


@app.patch("/api/services/{service_id}")
def update_service(service_id: int, data: ServiceUpdate, db: Db):
    begin_write(db)
    service = db.scalar(select(Service).where(Service.id == service_id).with_for_update())
    if service is None:
        raise HTTPException(404, "Serviço não encontrado")
    changes = data.model_dump(exclude_unset=True)
    if not changes or any(value is None for value in changes.values()):
        raise HTTPException(422, "Informe campos válidos para editar o serviço")
    if changes.get("active") is False and has_future_booking(db, Appointment.service_id == service_id):
        raise HTTPException(409, "Cancele ou conclua os agendamentos futuros antes de inativar o serviço")
    for field, value in changes.items():
        setattr(service, field, value)
    db.commit()
    return service_data(service)


@app.get("/api/professionals")
def list_professionals(db: Db):
    query = select(Professional).options(selectinload(Professional.services), selectinload(Professional.work_periods)).order_by(Professional.id)
    return [professional_data(p) for p in db.scalars(query)]


@app.post("/api/professionals", status_code=201)
def create_professional(data: ProfessionalInput, db: Db):
    ids = set(data.service_ids)
    services = list(db.scalars(select(Service).where(Service.id.in_(ids), Service.active)))
    if len(services) != len(ids):
        raise HTTPException(422, "Um ou mais serviços não existem ou estão inativos")
    professional = Professional(name=data.name, services=services)
    db.add(professional)
    db.commit()
    db.refresh(professional)
    return professional_data(professional)


@app.patch("/api/professionals/{professional_id}")
def update_professional(professional_id: int, data: ProfessionalUpdate, db: Db):
    begin_write(db)
    professional = db.scalar(select(Professional).options(selectinload(Professional.services), selectinload(Professional.work_periods))
                             .where(Professional.id == professional_id).with_for_update())
    if professional is None:
        raise HTTPException(404, "Profissional não encontrado")
    changes = data.model_dump(exclude_unset=True)
    if not changes or any(value is None for value in changes.values()):
        raise HTTPException(422, "Informe campos válidos para editar o profissional")
    if changes.get("active") is False and has_future_booking(db, Appointment.professional_id == professional_id):
        raise HTTPException(409, "Cancele ou conclua os agendamentos futuros antes de inativar o profissional")
    if "service_ids" in changes:
        ids = set(changes.pop("service_ids"))
        existing_ids = {service.id for service in professional.services}
        services = list(db.scalars(select(Service).where(Service.id.in_(ids))))
        if len(services) != len(ids) or any(not service.active and service.id not in existing_ids for service in services):
            raise HTTPException(422, "Um ou mais serviços não existem ou estão inativos")
        removed = {service.id for service in professional.services} - ids
        if removed and has_future_booking(db, Appointment.professional_id == professional_id,
                                          Appointment.service_id.in_(removed)):
            raise HTTPException(409, "Há agendamentos futuros para um serviço que seria removido")
        professional.services = services
    for field, value in changes.items():
        setattr(professional, field, value)
    db.commit()
    return professional_data(professional)


@app.get("/api/customers")
def list_customers(db: Db, q: str | None = Query(default=None, max_length=120)):
    query = select(Customer).order_by(Customer.name)
    if q:
        digits = re.sub(r"\D", "", q)
        condition = Customer.name.ilike(f"%{q}%")
        if len(digits) >= 3:
            condition |= Customer.phone.like(f"%{digits}%")
        query = query.where(condition)
    return [customer_data(db, customer) for customer in db.scalars(query)]


@app.post("/api/customers", status_code=201)
def create_customer(data: CustomerInput, db: Db):
    customer = Customer(**data.model_dump())
    db.add(customer)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Já existe um cliente com este telefone") from None
    return customer_data(db, customer)


@app.patch("/api/customers/{customer_id}")
def update_customer(customer_id: int, data: CustomerUpdate, db: Db):
    begin_write(db)
    customer = db.scalar(select(Customer).where(Customer.id == customer_id).with_for_update())
    if customer is None:
        raise HTTPException(404, "Cliente não encontrado")
    changes = data.model_dump(exclude_unset=True)
    if not changes or any(value is None for field, value in changes.items() if field != "email"):
        raise HTTPException(422, "Informe campos válidos para editar o cliente")
    old_phone = customer.phone
    for field, value in changes.items():
        setattr(customer, field, value)
    if customer.phone != old_phone:
        for appointment in db.scalars(select(Appointment).where(Appointment.customer_phone == old_phone)):
            appointment.customer_phone = customer.phone
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Já existe um cliente com este telefone") from None
    return customer_data(db, customer)


@app.get("/api/customers/{customer_id}/appointments")
def customer_appointments(customer_id: int, db: Db):
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(404, "Cliente não encontrado")
    query = select(Appointment).options(selectinload(Appointment.professional)).where(
        Appointment.customer_phone == customer.phone).order_by(Appointment.starts_at.desc()).limit(100)
    return [appointment_data(appointment) for appointment in db.scalars(query)]


@app.put("/api/professionals/{professional_id}/work-periods")
def replace_work_periods(professional_id: int, periods: list[PeriodInput], db: Db):
    begin_write(db)
    professional = db.scalar(select(Professional).options(selectinload(Professional.services), selectinload(Professional.work_periods))
                             .where(Professional.id == professional_id).with_for_update())
    if professional is None:
        raise HTTPException(404, "Profissional não encontrado")
    if not periods:
        raise HTTPException(422, "Informe pelo menos um período de trabalho")
    by_weekday: dict[int, list[PeriodInput]] = {}
    for period in periods:
        if period.starts_at >= period.ends_at:
            raise HTTPException(422, "O fim do período deve ser após o início")
        by_weekday.setdefault(period.weekday, []).append(period)
    for day_periods in by_weekday.values():
        ordered = sorted(day_periods, key=lambda p: p.starts_at)
        if any(left.ends_at > right.starts_at for left, right in zip(ordered, ordered[1:])):
            raise HTTPException(422, "Os períodos de trabalho não podem se sobrepor")
    future = db.scalars(select(Appointment).where(Appointment.professional_id == professional_id,
                                                   Appointment.status.in_(OPEN_STATUSES),
                                                   Appointment.starts_at >= datetime.now(timezone.utc))).all()
    for appointment in future:
        local_start = as_utc(appointment.starts_at).astimezone(ZONE)
        local_end = as_utc(appointment.ends_at).astimezone(ZONE)
        if not any(p.weekday == local_start.weekday() and p.starts_at <= local_start.time().replace(tzinfo=None)
                   and local_end.date() == local_start.date() and local_end.time().replace(tzinfo=None) <= p.ends_at for p in periods):
            raise HTTPException(409, "A nova jornada deixaria um agendamento fora do expediente")
    professional.work_periods = [WorkPeriod(**p.model_dump()) for p in periods]
    db.commit()
    db.refresh(professional)
    return professional_data(professional)


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
    if not any(p.weekday == start.weekday() and p.starts_at <= local_start and local_end <= p.ends_at
               for p in professional.work_periods):
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


def remember_customer(db: Session, name: str, phone: str) -> None:
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
        return
    db.execute(statement)


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


def reserve(data: BookingInput, db: Session) -> dict:
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
            remember_customer(db, data.customer_name.strip(), data.customer_phone)
            db.commit()
            db.refresh(appointment)
            return appointment_data(appointment)
    raise HTTPException(409, "Horário indisponível; escolha outro horário")


@app.post("/api/public/appointments", status_code=201)
def create_public_appointment(data: BookingInput, db: Db):
    return reserve(data, db)


@app.post("/api/appointments", status_code=201)
def create_internal_appointment(data: BookingInput, db: Db):
    return reserve(data, db)


@app.get("/api/appointments")
def list_appointments(db: Db, day: date = Query(default_factory=lambda: datetime.now(ZONE).date()),
                      view: Literal["day", "week"] = "day", professional_id: int | None = None):
    start, end = agenda_range(day, view)
    query = select(Appointment).options(selectinload(Appointment.professional)).where(
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
                view: Literal["day", "week"] = "day", professional_id: int | None = None):
    start, end = agenda_range(day, view)
    query = select(ScheduleBlock).options(selectinload(ScheduleBlock.professional)).where(
        ScheduleBlock.starts_at < end, ScheduleBlock.ends_at > start).order_by(ScheduleBlock.starts_at)
    if professional_id is not None:
        query = query.where(ScheduleBlock.professional_id == professional_id)
    return [block_data(block) for block in db.scalars(query)]


@app.post("/api/blocks", status_code=201)
def create_block(data: BlockInput, db: Db):
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
    db.commit()
    db.refresh(block)
    return block_data(block)


@app.delete("/api/blocks/{block_id}", status_code=204)
def delete_block(block_id: int, db: Db):
    begin_write(db)
    block = db.get(ScheduleBlock, block_id)
    if block is None:
        raise HTTPException(404, "Bloqueio não encontrado")
    db.delete(block)
    db.commit()


@app.post("/api/appointments/{appointment_id}/reschedule")
def reschedule_appointment(appointment_id: int, data: RescheduleInput, db: Db):
    begin_write(db)
    professional = db.scalar(select(Professional).options(selectinload(Professional.services),
        selectinload(Professional.work_periods)).where(Professional.id == data.professional_id).with_for_update())
    if professional is None or not professional.active:
        raise HTTPException(404, "Profissional ativo não encontrado")
    appointment = db.scalar(select(Appointment).where(Appointment.id == appointment_id)
                            .with_for_update().execution_options(populate_existing=True))
    if appointment is None:
        raise HTTPException(404, "Agendamento não encontrado")
    if appointment.status != "scheduled":
        raise HTTPException(409, "Somente agendamentos pendentes podem ser reagendados")
    service = db.get(Service, appointment.service_id)
    if service is None or not service.active or service not in professional.services:
        raise HTTPException(422, "Profissional não atende este serviço ativo")
    duration = int((as_utc(appointment.ends_at) - as_utc(appointment.starts_at)).total_seconds() / 60)
    start, end = validate_booking_time(data.starts_at, duration)
    if not is_available(db, professional, start, end, exclude_appointment_id=appointment.id):
        raise HTTPException(409, "Horário indisponível; escolha outro horário")
    appointment.professional_id = professional.id
    appointment.starts_at = start.astimezone(timezone.utc)
    appointment.ends_at = end.astimezone(timezone.utc)
    db.commit()
    db.refresh(appointment)
    return appointment_data(appointment)


@app.patch("/api/appointments/{appointment_id}/status")
def update_appointment_status(appointment_id: int, data: StatusInput, db: Db):
    begin_write(db)
    appointment = db.scalar(select(Appointment).where(Appointment.id == appointment_id).with_for_update())
    if appointment is None:
        raise HTTPException(404, "Agendamento não encontrado")
    allowed = {"scheduled": {"in_progress", "cancelled", "no_show"},
               "in_progress": {"completed", "cancelled"}}
    if data.status not in allowed.get(appointment.status, set()):
        raise HTTPException(409, "Mudança de status não permitida")
    if data.status == "no_show" and as_utc(appointment.starts_at) > datetime.now(timezone.utc):
        raise HTTPException(409, "A falta só pode ser registrada após o horário marcado")
    appointment.status = data.status
    db.commit()
    db.refresh(appointment)
    return appointment_data(appointment)

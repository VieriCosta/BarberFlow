from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
import re
from .auth import Actor, current_user, staff, administrator, audit
from .models import Appointment, Customer, Professional, Service, WorkPeriod
from .schemas import ServiceInput, ServiceUpdate, ProfessionalInput, ProfessionalUpdate, CustomerInput, CustomerUpdate, PeriodInput
from .booking import Db, service_data, professional_data, customer_data, appointment_data, begin_write, has_future_booking, as_utc, ZONE, OPEN_STATUSES

app = APIRouter(tags=["Catalog"])

@app.get("/services", dependencies=[Depends(current_user)])
def list_services(db: Db):
    return [service_data(s) for s in db.scalars(select(Service).order_by(Service.id))]


@app.post("/services", status_code=201, dependencies=[Depends(administrator)])
def create_service(data: ServiceInput, db: Db, actor: Actor):
    service = Service(**data.model_dump())
    db.add(service)
    db.flush()
    audit(db, "create_service", service.id, actor)
    db.commit()
    db.refresh(service)
    return service_data(service)


@app.patch("/services/{service_id}", dependencies=[Depends(administrator)])
def update_service(service_id: int, data: ServiceUpdate, db: Db, actor: Actor):
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
    db.flush()
    audit(db, "update_service", service.id, actor)
    db.commit()
    return service_data(service)


@app.get("/professionals", dependencies=[Depends(current_user)])
def list_professionals(db: Db):
    query = select(Professional).options(selectinload(Professional.services), selectinload(Professional.work_periods)).order_by(Professional.id)
    return [professional_data(p) for p in db.scalars(query)]


@app.post("/professionals", status_code=201, dependencies=[Depends(administrator)])
def create_professional(data: ProfessionalInput, db: Db, actor: Actor):
    ids = set(data.service_ids)
    services = list(db.scalars(select(Service).where(Service.id.in_(ids), Service.active)))
    if len(services) != len(ids):
        raise HTTPException(422, "Um ou mais serviços não existem ou estão inativos")
    professional = Professional(name=data.name, services=services)
    db.add(professional)
    db.flush()
    audit(db, "create_professional", professional.id, actor)
    db.commit()
    db.refresh(professional)
    return professional_data(professional)


@app.patch("/professionals/{professional_id}", dependencies=[Depends(administrator)])
def update_professional(professional_id: int, data: ProfessionalUpdate, db: Db, actor: Actor):
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
    db.flush()
    audit(db, "update_professional", professional.id, actor)
    db.commit()
    return professional_data(professional)


@app.get("/customers", dependencies=[Depends(staff)])
def list_customers(db: Db, q: str | None = Query(default=None, max_length=120)):
    query = select(Customer).order_by(Customer.name)
    if q:
        digits = re.sub(r"\D", "", q)
        condition = Customer.name.ilike(f"%{q}%")
        if len(digits) >= 3:
            condition |= Customer.phone.like(f"%{digits}%")
        query = query.where(condition)
    return [customer_data(db, customer) for customer in db.scalars(query)]


@app.post("/customers", status_code=201, dependencies=[Depends(staff)])
def create_customer(data: CustomerInput, db: Db, actor: Actor):
    customer = Customer(**data.model_dump())
    db.add(customer)
    try:
        db.flush()
        audit(db, "create_customer", customer.id, actor)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Já existe um cliente com este telefone") from None
    return customer_data(db, customer)


@app.patch("/customers/{customer_id}", dependencies=[Depends(staff)])
def update_customer(customer_id: int, data: CustomerUpdate, db: Db, actor: Actor):
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
        for appointment in db.scalars(select(Appointment).where(Appointment.customer_id == customer.id)):
            appointment.customer_phone = customer.phone
    try:
        db.flush()
        audit(db, "update_customer", customer.id, actor)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Já existe um cliente com este telefone") from None
    return customer_data(db, customer)


@app.get("/customers/{customer_id}/appointments", dependencies=[Depends(staff)])
def customer_appointments(customer_id: int, db: Db):
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(404, "Cliente não encontrado")
    query = select(Appointment).options(selectinload(Appointment.professional)).where(
        Appointment.customer_id == customer.id).order_by(Appointment.starts_at.desc()).limit(100)
    return [appointment_data(appointment) for appointment in db.scalars(query)]


@app.put("/professionals/{professional_id}/work-periods", dependencies=[Depends(administrator)])
def replace_work_periods(professional_id: int, periods: list[PeriodInput], db: Db, actor: Actor):
    begin_write(db)
    professional = db.scalar(select(Professional).options(selectinload(Professional.services), selectinload(Professional.work_periods))
                             .where(Professional.id == professional_id).with_for_update())
    if professional is None:
        raise HTTPException(404, "Profissional não encontrado")
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
        from .models import ScheduleException
        from .schedule import day_periods
        exception = db.scalar(select(ScheduleException).where(ScheduleException.professional_id == professional_id,
                                                            ScheduleException.day == local_start.date().isoformat()))
        effective = day_periods(db, professional, local_start.date()) if exception else [(p.starts_at, p.ends_at) for p in periods if p.weekday == local_start.weekday()]
        if not any(a <= local_start.time().replace(tzinfo=None) and local_end.date() == local_start.date()
                   and local_end.time().replace(tzinfo=None) <= b for a, b in effective):
            raise HTTPException(409, "A nova jornada deixaria um agendamento fora do expediente")
    professional.work_periods = [WorkPeriod(**p.model_dump()) for p in periods]
    db.flush()
    audit(db, "replace_work_periods", professional.id, actor)
    db.commit()
    db.refresh(professional)
    return professional_data(professional)



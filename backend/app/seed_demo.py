"""Optional demo data: run from backend with python -m app.seed_demo."""

import os
import sqlite3
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .database import Base, SessionLocal, engine
from .models import Appointment, Barbershop, Customer, Professional, ScheduleBlock, Service, WorkPeriod


ZONE = ZoneInfo(os.getenv("BARBERFLOW_TIMEZONE", "America/Fortaleza"))
MARKER = "Dados fictícios para demonstração do BarberFlow."
SERVICES = [
    ("Corte clássico (Demo)", "Corte com tesoura e máquina.", "40.00", 30),
    ("Barba completa (Demo)", "Desenho da barba e acabamento.", "30.00", 30),
    ("Corte + barba (Demo)", "Atendimento completo para cabelo e barba.", "65.00", 60),
    ("Degradê (Demo)", "Degradê com acabamento detalhado.", "50.00", 45),
    ("Corte infantil (Demo)", "Corte para os pequenos.", "35.00", 30),
]
TEAM = [
    ("Lucas Almeida (Demo)", [0, 1, 2, 3]),
    ("Rafael Costa (Demo)", [0, 1, 2, 4]),
    ("Camila Santos (Demo)", [0, 3, 4]),
]
NAMES = ["Pedro Lima", "Bruno Rocha", "Gabriel Alves", "Mateus Souza",
         "André Martins", "Felipe Oliveira", "Diego Pereira", "João Ribeiro"]


def seed_demo(db: Session, today: date | None = None) -> dict[str, int]:
    """Add missing demo records without replacing existing catalog or schedules."""
    today = today or datetime.now(ZONE).date()
    if db.info.get("shop_id") not in (None, 1):
        raise ValueError("A carga Demo pertence somente à barbearia inicial")
    db.info["shop_id"] = 1
    counts = dict(services=0, professionals=0, customers=0, appointments=0, blocks=0)
    if db.bind.dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))
    shop = db.get(Barbershop, 1)
    if shop is None:
        shop = Barbershop(id=1, name="Barbearia BarberFlow (Demo)", slug="barberflow", published=True)
        db.add(shop)
        db.flush()
    elif shop.name == "Barbearia BarberFlow":
        shop.name, shop.published = "Barbearia BarberFlow (Demo)", True

    services = []
    for name, description, price, duration in SERVICES:
        service = db.scalar(select(Service).where(Service.name == name))
        if service is None:
            service = Service(name=name, description=description, price=Decimal(price), duration_minutes=duration)
            db.add(service)
            counts["services"] += 1
        services.append(service)
    db.flush()

    team = []
    for name, indices in TEAM:
        professional = db.scalar(select(Professional).where(Professional.name == name).with_for_update())
        if professional is None:
            professional = Professional(name=name, services=[services[i] for i in indices], work_periods=[
                WorkPeriod(weekday=weekday, starts_at=start, ends_at=end)
                for weekday in range(6)
                for start, end in [(time(9), time(12)), (time(13), time(18))]
            ])
            db.add(professional)
            counts["professionals"] += 1
        team.append(professional)
    db.flush()

    customers = []
    for index, name in enumerate(NAMES):
        # Deliberately invalid subscriber numbers: illustrative, never contact them.
        phone = f"850000000{index:02d}"
        customer = db.scalar(select(Customer).where(Customer.phone == phone))
        if customer is None:
            customer = Customer(name=f"{name} (Demo)", phone=phone,
                                email=f"cliente{index + 1}@example.com", notes=MARKER)
            db.add(customer)
            counts["customers"] += 1
        customers.append(customer)
    db.flush()

    def business_day(day: date, step: int) -> date:
        while day.weekday() == 6:
            day += timedelta(days=step)
        return day

    upcoming = business_day(today + timedelta(days=1), 1)
    previous = business_day(today - timedelta(days=1), -1)

    def instant(day: date, hour: int, minute: int = 0) -> datetime:
        return datetime.combine(day, time(hour, minute), ZONE).astimezone(timezone.utc)

    def available(professional: Professional, start: datetime, end: datetime) -> bool:
        local_start, local_end = start.astimezone(ZONE), end.astimezone(ZONE)
        if not professional.active or not any(
            p.weekday == local_start.weekday() and p.starts_at <= local_start.time()
            and local_end.time() <= p.ends_at for p in professional.work_periods
        ):
            return False
        if db.scalar(select(Appointment.id).where(
            Appointment.professional_id == professional.id,
            Appointment.status.in_(["scheduled", "in_progress", "completed"]),
            Appointment.starts_at < end, Appointment.ends_at > start,
        ).limit(1)) is not None:
            return False
        return db.scalar(select(ScheduleBlock.id).where(
            ScheduleBlock.professional_id == professional.id,
            ScheduleBlock.starts_at < end, ScheduleBlock.ends_at > start,
        ).limit(1)) is None

    examples = [
        (0, 0, 0, upcoming, 9, 0, "scheduled"),
        (1, 2, 1, upcoming, 10, 0, "scheduled"),
        (2, 3, 2, upcoming, 9, 0, "scheduled"),
        (0, 1, 3, upcoming, 14, 0, "scheduled"),
        (1, 4, 4, upcoming, 15, 0, "scheduled"),
        (2, 0, 5, upcoming, 16, 0, "scheduled"),
        (0, 0, 0, previous, 9, 0, "completed"),
        (1, 2, 1, previous, 10, 0, "completed"),
        (2, 3, 6, previous, 14, 0, "cancelled"),
        (0, 1, 7, previous, 15, 0, "no_show"),
    ]
    for team_index, service_index, customer_index, day, hour, minute, status in examples:
        professional, service, customer = team[team_index], services[service_index], customers[customer_index]
        start = instant(day, hour, minute)
        end = start + timedelta(minutes=service.duration_minutes)
        exists = db.scalar(select(Appointment.id).where(
            Appointment.professional_id == professional.id, Appointment.starts_at == start,
            Appointment.customer_phone == customer.phone,
        ).limit(1))
        if exists is not None or not service.active or service not in professional.services:
            continue
        if not available(professional, start, end):
            continue
        db.add(Appointment(service_id=service.id, service_name=service.name,
                           professional_id=professional.id, customer_id=customer.id, customer_name=customer.name,
                           customer_phone=customer.phone, starts_at=start, ends_at=end,
                           price=service.price, status=status))
        db.flush()
        counts["appointments"] += 1

    for professional in team:
        start, end = instant(upcoming, 16, 30), instant(upcoming, 17)
        if available(professional, start, end):
            db.add(ScheduleBlock(professional_id=professional.id, starts_at=start, ends_at=end,
                                 reason="Pausa da equipe (Demo)"))
            db.flush()
            counts["blocks"] += 1
    db.commit()
    return counts


def main() -> None:
    if engine.dialect.name == "sqlite" and engine.url.database not in (None, ":memory:"):
        database = Path(engine.url.database).resolve()
        if database.exists():
            backup = database.with_name(f"{database.stem}.backup-{datetime.now(timezone.utc):%Y%m%d-%H%M%S-%f}.db")
            with closing(sqlite3.connect(database)) as source, closing(sqlite3.connect(backup)) as destination:
                source.backup(destination)
            print(f"Backup criado: {backup.name}")
    from .migrations import migrate
    migrate()
    with SessionLocal() as db:
        counts = seed_demo(db)
    print("Dados Demo adicionados: " + ", ".join(f"{key}={value}" for key, value in counts.items()))


if __name__ == "__main__":
    main()

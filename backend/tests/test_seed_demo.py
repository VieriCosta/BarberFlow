from datetime import date

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Appointment, Professional, ScheduleBlock, Service
from app.seed_demo import seed_demo


def test_seed_is_repeatable_and_preserves_existing_data():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Service(name="Serviço real", price=99, duration_minutes=20))
        db.commit()
        counts = seed_demo(db, date(2026, 10, 6))
        assert counts == dict(services=5, professionals=3, customers=8, appointments=10, blocks=3)
        assert all(value == 0 for value in seed_demo(db, date(2026, 10, 6)).values())
        assert db.scalar(select(Service.price).where(Service.name == "Serviço real")) == 99
        assert db.scalar(select(func.count()).select_from(Appointment)) == 10


def test_seed_preserves_edited_schedule_and_skips_conflicting_slots():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        seed_demo(db, date(2026, 10, 10))  # Saturday: future reservations on Monday.
        assert all(a.starts_at.weekday() != 6 for a in db.scalars(select(Appointment)))
        professional = db.scalar(select(Professional).where(Professional.name == "Lucas Almeida (Demo)"))
        professional.work_periods = []
        db.commit()
        counts = seed_demo(db, date(2026, 10, 10))
        assert professional.work_periods == []
        assert counts["appointments"] == 0
        assert counts["blocks"] == 0
        assert db.scalar(select(func.count()).select_from(ScheduleBlock)) == 3

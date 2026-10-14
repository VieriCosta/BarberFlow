from datetime import datetime, time
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Table, Column, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


professional_services = Table(
    "professional_services",
    Base.metadata,
    Column("professional_id", ForeignKey("professionals.id", ondelete="CASCADE"), primary_key=True),
    Column("service_id", ForeignKey("services.id", ondelete="CASCADE"), primary_key=True),
)


class Service(Base):
    __tablename__ = "services"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="")
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    professionals: Mapped[list["Professional"]] = relationship(secondary=professional_services, back_populates="services")
    __table_args__ = (CheckConstraint("duration_minutes > 0"), CheckConstraint("price >= 0"))


class Professional(Base):
    __tablename__ = "professionals"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    services: Mapped[list[Service]] = relationship(secondary=professional_services, back_populates="professionals")
    work_periods: Mapped[list["WorkPeriod"]] = relationship(back_populates="professional", cascade="all, delete-orphan")


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str] = mapped_column(String(1000), default="", nullable=False)


class WorkPeriod(Base):
    __tablename__ = "work_periods"
    id: Mapped[int] = mapped_column(primary_key=True)
    professional_id: Mapped[int] = mapped_column(ForeignKey("professionals.id"), nullable=False)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)  # Monday = 0
    starts_at: Mapped[time] = mapped_column(Time, nullable=False)
    ends_at: Mapped[time] = mapped_column(Time, nullable=False)
    professional: Mapped[Professional] = relationship(back_populates="work_periods")
    __table_args__ = (CheckConstraint("weekday >= 0 AND weekday <= 6"), CheckConstraint("starts_at < ends_at"), UniqueConstraint("professional_id", "weekday", "starts_at", "ends_at"))


class Appointment(Base):
    __tablename__ = "appointments"
    id: Mapped[int] = mapped_column(primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"), nullable=False)
    professional_id: Mapped[int] = mapped_column(ForeignKey("professionals.id"), nullable=False)
    customer_name: Mapped[str] = mapped_column(String(120), nullable=False)
    customer_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    service_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="scheduled", nullable=False)
    service: Mapped[Service] = relationship()
    professional: Mapped[Professional] = relationship()
    __table_args__ = (CheckConstraint("starts_at < ends_at"),)


class ScheduleBlock(Base):
    __tablename__ = "schedule_blocks"
    id: Mapped[int] = mapped_column(primary_key=True)
    professional_id: Mapped[int] = mapped_column(ForeignKey("professionals.id"), nullable=False, index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    professional: Mapped[Professional] = relationship()
    __table_args__ = (CheckConstraint("starts_at < ends_at"),)

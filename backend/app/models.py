from datetime import datetime, time
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Table, Column, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base, ShopScoped


class Barbershop(Base):
    __tablename__ = "barbershops"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="")
    city: Mapped[str] = mapped_column(String(120), default="")
    address: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(20), default="")
    published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


professional_services = Table(
    "professional_services",
    Base.metadata,
    Column("professional_id", ForeignKey("professionals.id", ondelete="CASCADE"), primary_key=True),
    Column("service_id", ForeignKey("services.id", ondelete="CASCADE"), primary_key=True),
)


class Service(ShopScoped, Base):
    __tablename__ = "services"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="")
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    professionals: Mapped[list["Professional"]] = relationship(secondary=professional_services, back_populates="services")
    __table_args__ = (CheckConstraint("duration_minutes > 0"), CheckConstraint("price >= 0"))


class Professional(ShopScoped, Base):
    __tablename__ = "professionals"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    services: Mapped[list[Service]] = relationship(secondary=professional_services, back_populates="professionals")
    work_periods: Mapped[list["WorkPeriod"]] = relationship(back_populates="professional", cascade="all, delete-orphan")


class Customer(ShopScoped, Base):
    __table_args__ = (UniqueConstraint("shop_id", "phone", name="uq_customers_shop_phone"),)
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str] = mapped_column(String(1000), default="", nullable=False)


class WorkPeriod(ShopScoped, Base):
    __tablename__ = "work_periods"
    id: Mapped[int] = mapped_column(primary_key=True)
    professional_id: Mapped[int] = mapped_column(ForeignKey("professionals.id"), nullable=False)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)  # Monday = 0
    starts_at: Mapped[time] = mapped_column(Time, nullable=False)
    ends_at: Mapped[time] = mapped_column(Time, nullable=False)
    professional: Mapped[Professional] = relationship(back_populates="work_periods")
    __table_args__ = (CheckConstraint("weekday >= 0 AND weekday <= 6"), CheckConstraint("starts_at < ends_at"), UniqueConstraint("professional_id", "weekday", "starts_at", "ends_at"))


class Appointment(ShopScoped, Base):
    __tablename__ = "appointments"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True, index=True)
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
    payment: Mapped["Payment | None"] = relationship(uselist=False)
    __table_args__ = (CheckConstraint("starts_at < ends_at"),)


class ScheduleBlock(ShopScoped, Base):
    __tablename__ = "schedule_blocks"
    id: Mapped[int] = mapped_column(primary_key=True)
    professional_id: Mapped[int] = mapped_column(ForeignKey("professionals.id"), nullable=False, index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    professional: Mapped[Professional] = relationship()
    __table_args__ = (CheckConstraint("starts_at < ends_at"),)


class User(ShopScoped, Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))
    professional_id: Mapped[int | None] = mapped_column(ForeignKey("professionals.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (CheckConstraint("role IN ('admin', 'reception', 'barber')"), UniqueConstraint("shop_id", "username", name="uq_users_shop_username"))


class LoginSession(ShopScoped, Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BookingAccess(ShopScoped, Base):
    __tablename__ = "booking_access"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id"), unique=True)


class AuditEvent(ShopScoped, Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Payment(ShopScoped, Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id"), unique=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    discount: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    method: Mapped[str] = mapped_column(String(20))
    commission: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    __table_args__ = (CheckConstraint("amount >= 0 AND discount >= 0 AND commission >= 0 AND commission <= amount"),)


class Expense(ShopScoped, Base):
    __tablename__ = "expenses"
    id: Mapped[int] = mapped_column(primary_key=True)
    description: Mapped[str] = mapped_column(String(200))
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    method: Mapped[str] = mapped_column(String(20))
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    __table_args__ = (CheckConstraint("amount > 0"),)


class CashClose(ShopScoped, Base):
    __table_args__ = (UniqueConstraint("shop_id", "day", name="uq_cash_closes_shop_day"),)
    __tablename__ = "cash_closes"
    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[str] = mapped_column(String(10))
    received: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    expenses: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    cash_expected: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    cash_counted: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    notes: Mapped[str] = mapped_column(String(1000), default="")
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ScheduleException(ShopScoped, Base):
    __tablename__ = "schedule_exceptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    professional_id: Mapped[int] = mapped_column(ForeignKey("professionals.id"), index=True)
    day: Mapped[str] = mapped_column(String(10))
    reason: Mapped[str] = mapped_column(String(200), default="")
    # One row per day replaces the regular work schedule; empty JSON means closed.
    periods_json: Mapped[str] = mapped_column(String(2000), default="[]")
    __table_args__ = (UniqueConstraint("professional_id", "day"),)


class Notification(ShopScoped, Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    generation: Mapped[str] = mapped_column(String(32), default="")
    state: Mapped[str] = mapped_column(String(20), default="pending")
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(String(500), default="")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("appointment_id", "kind"),)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))

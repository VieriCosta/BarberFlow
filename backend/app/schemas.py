import re
from datetime import datetime, time
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, Field, field_validator

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
    customer_email: str | None = Field(default=None, max_length=255, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

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



import os
import smtplib
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from zoneinfo import ZoneInfo
import httpx
from sqlalchemy import select, text, or_, and_
from .database import SessionLocal
from .models import Appointment, Barbershop, Customer, Notification
from .auth import utc


def send(payload):
    webhook = os.getenv("BARBERFLOW_NOTIFICATION_WEBHOOK")
    if webhook:
        if not webhook.startswith("https://"):
            raise RuntimeError("O webhook deve usar HTTPS")
        headers = {"Idempotency-Key": str(payload["notification_id"])+":"+str(payload["version"])}
        secret = os.getenv("BARBERFLOW_NOTIFICATION_SECRET")
        if secret:
            headers["Authorization"] = "Bearer " + secret
        response = httpx.post(webhook, json=payload, headers=headers, timeout=20, follow_redirects=False)
        response.raise_for_status()
        return
    host = os.getenv("BARBERFLOW_SMTP_HOST")
    if not host:
        raise RuntimeError("Configure SMTP ou webhook para habilitar os envios")
    if not payload["email"]:
        raise RuntimeError("Cliente sem e-mail; configure webhook para enviar por telefone")
    message = EmailMessage()
    message["From"] = os.environ["BARBERFLOW_SMTP_FROM"]
    message["To"] = payload["email"]
    message["Subject"] = "BarberFlow — " + ("Lembrete do atendimento" if payload["kind"] == "reminder" else "Atualização da reserva")
    message.set_content(payload["message"])
    with smtplib.SMTP(host, int(os.getenv("BARBERFLOW_SMTP_PORT", "587")), timeout=20) as smtp:
        smtp.starttls()
        if os.getenv("BARBERFLOW_SMTP_USERNAME"):
            smtp.login(os.environ["BARBERFLOW_SMTP_USERNAME"], os.environ["BARBERFLOW_SMTP_PASSWORD"])
        smtp.send_message(message)


def deliver_once(factory=SessionLocal, sender=send):
    now = datetime.now(timezone.utc)
    with factory() as db:
        if db.bind.dialect.name == "sqlite":
            db.execute(text("BEGIN IMMEDIATE"))
        row = db.scalar(select(Notification).where(or_(
            and_(Notification.state == "pending", Notification.due_at <= now),
            and_(Notification.state == "processing", Notification.locked_at < now-timedelta(minutes=10))
        )).order_by(Notification.due_at).with_for_update(skip_locked=True).limit(1))
        if row is None:
            return False
        appointment = db.get(Appointment, row.appointment_id)
        if appointment.status != "scheduled" or utc(appointment.starts_at) <= now:
            row.state = "cancelled"
            db.commit()
            return True
        customer = db.get(Customer, appointment.customer_id) if appointment.customer_id else None
        shop = db.get(Barbershop, appointment.shop_id)
        shop_name = shop.name if shop else "BarberFlow"
        zone = ZoneInfo(os.getenv("BARBERFLOW_TIMEZONE", "America/Fortaleza"))
        start = utc(appointment.starts_at).astimezone(zone)
        row.state, row.locked_at, row.attempts = "processing", now, row.attempts+1
        payload = dict(notification_id=row.id, version=row.generation, kind=row.kind,
                       shop_id=appointment.shop_id, shop_name=shop_name,
                       appointment_id=appointment.id, phone=customer.phone if customer else appointment.customer_phone,
                       email=customer.email if customer else None,
                       message=f"Olá, {appointment.customer_name}! Sua reserva em {shop_name}: {appointment.service_name} com {appointment.professional.name}, {start:%d/%m/%Y às %H:%M}.")
        notification_id = row.id
        db.commit()
    error = ""
    try:
        sender(payload)
    except Exception as exc:
        # Avoid storing provider responses, credentials or recipient addresses.
        error = type(exc).__name__ + ": envio não concluído; verifique a configuração do provedor"
    with factory() as db:
        row = db.scalar(select(Notification).where(Notification.id == notification_id).with_for_update())
        if row.state != "processing" or row.locked_at is None or utc(row.locked_at) != now:
            return True
        row.locked_at = None
        if error:
            row.last_error = error
            row.state = "failed" if row.attempts >= 5 else "pending"
            row.due_at = datetime.now(timezone.utc) + timedelta(minutes=2**row.attempts)
        else:
            row.state, row.sent_at, row.last_error = "sent", datetime.now(timezone.utc), ""
        db.commit()
    return True


if __name__ == "__main__":
    if not (os.getenv("BARBERFLOW_NOTIFICATION_WEBHOOK") or os.getenv("BARBERFLOW_SMTP_HOST")):
        raise SystemExit("Configure SMTP ou webhook antes de iniciar o worker")
    while True:
        if not deliver_once():
            time.sleep(5)

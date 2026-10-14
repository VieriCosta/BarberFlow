"""Versioned, additive migrations for SQLite and PostgreSQL. Run before serving."""
from datetime import datetime, timezone
import sqlite3
from pathlib import Path
from sqlalchemy import inspect, text
from .database import Base, engine
from . import models  # register tables


def migrate(target=engine):
    existing = inspect(target).get_table_names()
    with target.connect() as connection:
        versions = set(connection.execute(text("SELECT version FROM schema_migrations")).scalars()) if "schema_migrations" in existing else set()
    if 2 not in versions and target.dialect.name == "sqlite" and "appointments" in existing and target.url.database not in (None, ":memory:"):
        path = Path(target.url.database).resolve()
        backup = path.with_name(f"{path.stem}.backup-migrate-{datetime.now(timezone.utc):%Y%m%d-%H%M%S-%f}.db")
        with sqlite3.connect(path) as source, sqlite3.connect(backup) as destination:
            source.backup(destination)
    with target.begin() as connection:
        if target.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(73481291)"))
        connection.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)"))
        versions = set(connection.execute(text("SELECT version FROM schema_migrations")).scalars())
        if 1 not in versions:
            Base.metadata.create_all(connection)
            columns = {c["name"] for c in inspect(connection).get_columns("appointments")}
            if "customer_id" not in columns:
                connection.execute(text("ALTER TABLE appointments ADD COLUMN customer_id INTEGER REFERENCES customers(id)"))
                connection.execute(text("CREATE INDEX ix_appointments_customer_id ON appointments(customer_id)"))
            connection.execute(text("""UPDATE appointments SET customer_id =
                (SELECT id FROM customers WHERE customers.phone = appointments.customer_phone)
                WHERE customer_id IS NULL"""))
            connection.execute(text("INSERT INTO schema_migrations (version) VALUES (1)"))
        if 2 not in versions:
            models.LoginAttempt.__table__.create(connection, checkfirst=True)
            columns = {c["name"] for c in inspect(connection).get_columns("notifications")}
            if "locked_at" not in columns:
                kind = "TIMESTAMP WITH TIME ZONE" if target.dialect.name == "postgresql" else "DATETIME"
                connection.execute(text(f"ALTER TABLE notifications ADD COLUMN locked_at {kind}"))
            connection.execute(text("INSERT INTO schema_migrations (version) VALUES (2)"))


if __name__ == "__main__":
    migrate()
    print("Banco atualizado: versão 2")

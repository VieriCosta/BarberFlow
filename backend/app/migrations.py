"""Versioned, additive migrations for SQLite and PostgreSQL. Run before serving."""
from datetime import datetime, timezone
import sqlite3
from contextlib import closing
from pathlib import Path
from sqlalchemy import MetaData, inspect, text
from sqlalchemy.schema import CreateTable
from .database import Base, engine
from . import models  # register tables


def migrate_shop_scopes(connection):
    models.Barbershop.__table__.create(connection, checkfirst=True)
    count = connection.execute(text("SELECT COUNT(*) FROM professionals")).scalar()
    demo = connection.execute(text("SELECT COUNT(*) FROM professionals WHERE name LIKE '%(Demo)%'")).scalar()
    name = "Barbearia BarberFlow (Demo)" if count and count == demo else "Barbearia BarberFlow"
    if connection.execute(text("SELECT id FROM barbershops WHERE id = 1")).scalar() is None:
        connection.execute(models.Barbershop.__table__.insert().values(id=1, name=name, slug="barberflow", description="Cortes, barba e cuidado no seu tempo.", published=bool(count), city="", address="", phone=""))
    for table in Base.metadata.sorted_tables:
        if "shop_id" not in table.c:
            continue
        columns = {c["name"] for c in inspect(connection).get_columns(table.name)}
        if "shop_id" not in columns:
            connection.execute(text(f'ALTER TABLE {table.name} ADD COLUMN shop_id INTEGER NOT NULL DEFAULT 1 REFERENCES barbershops(id)'))
            connection.execute(text(f'CREATE INDEX ix_{table.name}_shop_id ON {table.name}(shop_id)'))

    # Phone, username and cash closing day must be unique within a shop, not globally.
    for model, column, constraint in [(models.Customer, "phone", "uq_customers_shop_phone"),
                                      (models.User, "username", "uq_users_shop_username"),
                                      (models.CashClose, "day", "uq_cash_closes_shop_day")]:
        table = model.__table__
        uniques = inspect(connection).get_unique_constraints(table.name)
        if any(set(u["column_names"]) == {"shop_id", column} for u in uniques):
            continue
        if connection.dialect.name == "sqlite":
            metadata = MetaData()
            for original in Base.metadata.tables.values():
                if original.name != table.name:
                    original.to_metadata(metadata)
            replacement = table.to_metadata(metadata, name=f"{table.name}_scoped")
            connection.execute(CreateTable(replacement))
            names = ", ".join(c.name for c in table.c)
            connection.execute(text(f'INSERT INTO {replacement.name} ({names}) SELECT {names} FROM {table.name}'))
            connection.execute(text(f'DROP TABLE {table.name}'))
            connection.execute(text(f'ALTER TABLE {replacement.name} RENAME TO {table.name}'))
            for index in table.indexes:
                index.create(connection, checkfirst=True)
        else:
            quote = connection.dialect.identifier_preparer.quote
            for unique in uniques:
                if unique["column_names"] == [column]:
                    connection.execute(text(f'ALTER TABLE {table.name} DROP CONSTRAINT {quote(unique["name"])}'))
            for index in inspect(connection).get_indexes(table.name):
                if index.get("unique") and index["column_names"] == [column] and not index.get("duplicates_constraint"):
                    connection.execute(text(f'DROP INDEX {quote(index["name"])}'))
            connection.execute(text(f'ALTER TABLE {table.name} ADD CONSTRAINT {constraint} UNIQUE (shop_id, {column})'))
            for index in table.indexes:
                index.create(connection, checkfirst=True)
    if connection.dialect.name == "postgresql":
        connection.execute(text("SELECT setval(pg_get_serial_sequence('barbershops', 'id'), (SELECT MAX(id) FROM barbershops))"))


def migrate(target=engine):
    existing = inspect(target).get_table_names()
    with target.connect() as connection:
        versions = set(connection.execute(text("SELECT version FROM schema_migrations")).scalars()) if "schema_migrations" in existing else set()
    if 4 not in versions and target.dialect.name == "sqlite" and "appointments" in existing and target.url.database not in (None, ":memory:"):
        path = Path(target.url.database).resolve()
        backup = path.with_name(f"{path.stem}.backup-migrate-{datetime.now(timezone.utc):%Y%m%d-%H%M%S-%f}.db")
        with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(backup)) as destination:
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
        if 3 not in versions:
            columns = {c["name"] for c in inspect(connection).get_columns("notifications")}
            if "generation" not in columns:
                connection.execute(text("ALTER TABLE notifications ADD COLUMN generation VARCHAR(32) NOT NULL DEFAULT ''"))
            connection.execute(text("INSERT INTO schema_migrations (version) VALUES (3)"))
        if 4 not in versions:
            migrate_shop_scopes(connection)
            connection.execute(text("INSERT INTO schema_migrations (version) VALUES (4)"))


if __name__ == "__main__":
    migrate()
    print("Banco atualizado: versão 4")

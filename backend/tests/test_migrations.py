from sqlalchemy import create_engine, text
from app.migrations import migrate
import os
import uuid
import pytest


def test_migrate_legacy_database_preserves_and_links_history(tmp_path):
    path = tmp_path / 'legacy.db'
    engine = create_engine(f'sqlite:///{path}')
    with engine.begin() as db:
        db.execute(text('CREATE TABLE customers (id INTEGER PRIMARY KEY, name VARCHAR(120), phone VARCHAR(20), email VARCHAR(255), notes VARCHAR(1000))'))
        db.execute(text('CREATE TABLE appointments (id INTEGER PRIMARY KEY, service_id INTEGER, professional_id INTEGER, customer_name VARCHAR(120), customer_phone VARCHAR(20), starts_at DATETIME, ends_at DATETIME, price NUMERIC, service_name VARCHAR(120), status VARCHAR(20))'))
        db.execute(text("INSERT INTO customers VALUES (1, 'Legacy customer', '85999991234', NULL, '')"))
        db.execute(text("INSERT INTO appointments VALUES (1, 1, 1, 'Legacy customer', '85999991234', '2026-01-01 12:00:00', '2026-01-01 12:30:00', 35, 'Corte', 'completed')"))
    migrate(engine)
    migrate(engine)
    with engine.connect() as db:
        assert db.execute(text('SELECT customer_id FROM appointments')).scalar() == 1
        assert db.execute(text('SELECT price FROM appointments')).scalar() == 35
        assert db.execute(text('SELECT COUNT(*) FROM schema_migrations')).scalar() == 3
    assert len(list(tmp_path.glob('legacy.backup-migrate-*.db'))) == 1
    engine.dispose()


def test_sqlite_backup_can_be_restored_and_retains_only_requested_count(tmp_path, monkeypatch):
    from app import backup as module
    import sqlite3
    engine = create_engine(f"sqlite:///{tmp_path / 'source.db'}")
    with engine.begin() as db:
        db.execute(text('CREATE TABLE example (id INTEGER PRIMARY KEY, name TEXT)'))
        db.execute(text("INSERT INTO example VALUES (1, 'Preserved record')"))
    monkeypatch.setattr(module, 'engine', engine)
    output = tmp_path / 'backups'
    module.backup(output, keep=1)
    latest = module.backup(output, keep=1)
    assert list(output.glob('barberflow-*.db')) == [latest]
    with sqlite3.connect(latest) as db:
        assert db.execute('SELECT name FROM example').fetchone()[0] == 'Preserved record'
    engine.dispose()


@pytest.mark.skipif(not os.getenv('TEST_DATABASE_URL'), reason='PostgreSQL de testes não configurado')
def test_postgres_legacy_migration_is_additive_and_repeatable():
    url = os.environ['TEST_DATABASE_URL']
    schema = 'migration_' + uuid.uuid4().hex
    maintenance = create_engine(url)
    with maintenance.begin() as db:
        db.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={'options': f'-csearch_path={schema}'})
    try:
        with engine.begin() as db:
            db.execute(text('CREATE TABLE customers (id INTEGER PRIMARY KEY, name VARCHAR(120), phone VARCHAR(20), email VARCHAR(255), notes VARCHAR(1000))'))
            db.execute(text('CREATE TABLE appointments (id INTEGER PRIMARY KEY, service_id INTEGER, professional_id INTEGER, customer_name VARCHAR(120), customer_phone VARCHAR(20), starts_at TIMESTAMP WITH TIME ZONE, ends_at TIMESTAMP WITH TIME ZONE, price NUMERIC, service_name VARCHAR(120), status VARCHAR(20))'))
            db.execute(text("INSERT INTO customers VALUES (1, 'Legacy customer', '85999991234', NULL, '')"))
            db.execute(text("INSERT INTO appointments VALUES (1, 1, 1, 'Legacy customer', '85999991234', '2026-01-01 12:00:00+00', '2026-01-01 12:30:00+00', 35, 'Corte', 'completed')"))
        migrate(engine)
        migrate(engine)
        with engine.connect() as db:
            assert db.execute(text('SELECT customer_id FROM appointments')).scalar() == 1
            assert db.execute(text('SELECT price FROM appointments')).scalar() == 35
            assert db.execute(text('SELECT COUNT(*) FROM schema_migrations')).scalar() == 3
    finally:
        engine.dispose()
        with maintenance.begin() as db:
            db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        maintenance.dispose()

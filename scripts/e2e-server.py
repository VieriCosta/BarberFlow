"""Isolated backend for browser tests; never reads or writes the real database."""
import os
from pathlib import Path
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
artifacts = root / '.test-artifacts'
artifacts.mkdir(exist_ok=True)
sys.path.insert(0, str(root / 'backend'))

with tempfile.TemporaryDirectory(prefix='e2e-', dir=artifacts) as directory:
    database = Path(directory) / 'test.db'
    os.environ['DATABASE_URL'] = 'sqlite:///' + database.as_posix()
    os.environ['BARBERFLOW_CORS_ORIGINS'] = 'http://127.0.0.1:14200'
    from app.database import SessionLocal, engine
    from app.migrations import migrate
    from app.seed_demo import seed_demo
    from app.auth import hash_password
    from app.models import User, Professional
    from sqlalchemy import select
    import uvicorn
    migrate()
    with SessionLocal() as db:
        seed_demo(db)
        professional = db.scalar(select(Professional).order_by(Professional.id))
        for username, role in [('admin', 'admin'), ('reception', 'reception'), ('barber', 'barber')]:
            db.add(User(username=username, name='E2E ' + role, role=role,
                        password_hash=hash_password('e2e-password-123'),
                        professional_id=professional.id if role == 'barber' else None))
        db.commit()
    try:
        uvicorn.run('app.main:app', host='127.0.0.1', port=18001)
    finally:
        engine.dispose()

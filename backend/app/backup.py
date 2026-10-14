"""Create and retain consistent SQLite backups; PostgreSQL uses the Compose backup service."""
import argparse
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from .database import engine


def backup(output: Path, keep: int = 14):
    if keep < 1:
        raise ValueError("A retenção deve ser de pelo menos um backup")
    if engine.dialect.name != "sqlite" or engine.url.database in (None, ':memory:'):
        raise ValueError("Para PostgreSQL, use o serviço de backup do Docker Compose")
    source_path = Path(engine.url.database).resolve()
    if not source_path.is_file():
        raise ValueError("Banco SQLite não encontrado")
    output.mkdir(parents=True, exist_ok=True)
    destination = output / f'barberflow-{datetime.now(timezone.utc):%Y%m%d-%H%M%S-%f}.db'
    with closing(sqlite3.connect(f'file:{source_path.as_posix()}?mode=ro', uri=True)) as source, closing(sqlite3.connect(destination)) as target:
        source.backup(target)
        if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError("A verificação de integridade do backup falhou")
    for old in sorted(output.glob('barberflow-*.db'), reverse=True)[keep:]:
        old.unlink()
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path('backups'))
    parser.add_argument('--keep', type=int, default=14)
    parser.add_argument('--interval', type=int, default=0, help='Segundos entre backups; zero executa apenas uma vez')
    args = parser.parse_args()
    if args.interval < 0:
        parser.error('O intervalo deve ser positivo')
    while True:
        print(f'Backup verificado: {backup(args.output, args.keep)}', flush=True)
        if not args.interval:
            break
        import time
        time.sleep(args.interval)

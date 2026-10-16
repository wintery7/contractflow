"""Docker 없이 쓰는 로컬 개발용 PostgreSQL 16 + pgvector.

pgserver 패키지에 포함된 PostgreSQL 바이너리를 사용한다. 데이터는 var/pgdata에 저장된다.
운영/배포용이 아니며, Docker 환경(docker-compose.yml)과 같은 계정·DB 이름을 쓴다.

    uv run python scripts/local_db.py start
    uv run python scripts/local_db.py status
    uv run python scripts/local_db.py stop
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pgserver

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "var" / "pgdata"
LOG_FILE = PROJECT_ROOT / "var" / "pgdata.log"
BIN_DIR = Path(pgserver.__file__).parent / "pginstall" / "bin"

USER = "contractflow"
PASSWORD = os.environ.get("POSTGRES_PASSWORD", "change-me")
PORT = os.environ.get("LOCAL_DB_PORT", "5432")
DATABASES = ("contractflow", "contractflow_test")


def _bin(name: str) -> str:
    return str(BIN_DIR / (f"{name}.exe" if sys.platform == "win32" else name))


def _run(*args: str, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess[str]:
    # pg_ctl start로 뜬 서버 프로세스가 출력 파이프를 물려받으면 호출한 쪽이 영원히 끝나지 않는다.
    # 그래서 pg_ctl은 capture=False(DEVNULL)로 실행하고, 서버 로그는 -l 파일로 남긴다.
    stream = subprocess.PIPE if capture else subprocess.DEVNULL
    return subprocess.run(
        args,
        check=check,
        stdin=subprocess.DEVNULL,
        stdout=stream,
        stderr=stream,
        text=True,
        env={**os.environ, "PGPASSWORD": PASSWORD},
    )


def _psql(database: str, sql: str) -> str:
    result = _run(
        _bin("psql"), "-h", "localhost", "-p", PORT, "-U", USER, "-d", database, "-tAc", sql
    )
    return result.stdout.strip()


def _is_running() -> bool:
    return _run(_bin("pg_isready"), "-h", "localhost", "-p", PORT, check=False).returncode == 0


def _init_cluster() -> None:
    DATA_DIR.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".pw") as pw:
        pw.write(PASSWORD)
    try:
        _run(
            _bin("initdb"),
            "-D", str(DATA_DIR),
            "-U", USER,
            "--pwfile", pw.name,
            "--auth", "scram-sha-256",
            "-E", "UTF8",
            "--locale", "C",
        )  # fmt: skip
    finally:
        Path(pw.name).unlink(missing_ok=True)
    print(f"initialized cluster at {DATA_DIR}")


def _ensure_databases() -> None:
    for database in DATABASES:
        exists = _psql("postgres", f"SELECT 1 FROM pg_database WHERE datname = '{database}'")
        if not exists:
            _psql("postgres", f"CREATE DATABASE {database}")
            print(f"created database {database}")
        _psql(database, "CREATE EXTENSION IF NOT EXISTS vector")


def start() -> None:
    if not (DATA_DIR / "PG_VERSION").exists():
        _init_cluster()
    if _is_running():
        print(f"already running on port {PORT}")
    else:
        _run(
            _bin("pg_ctl"), "-D", str(DATA_DIR), "-o", f"-p {PORT}",
            "-l", str(LOG_FILE), "-w", "start",
            capture=False,
        )  # fmt: skip
        print(f"started on port {PORT} (log: {LOG_FILE.relative_to(PROJECT_ROOT)})")
    _ensure_databases()
    version = _psql("contractflow", "SELECT extversion FROM pg_extension WHERE extname = 'vector'")
    print(f"ready: {', '.join(DATABASES)} (pgvector {version})")


def stop() -> None:
    if not _is_running():
        print("not running")
        return
    _run(_bin("pg_ctl"), "-D", str(DATA_DIR), "-m", "fast", "-w", "stop", capture=False)
    print("stopped")


def status() -> None:
    print(f"running on port {PORT}" if _is_running() else "not running")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["start", "stop", "status"])
    {"start": start, "stop": stop, "status": status}[parser.parse_args().command]()


if __name__ == "__main__":
    main()

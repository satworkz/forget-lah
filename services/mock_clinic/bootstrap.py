"""Provision once using bootstrap's owner connection; runtime never receives it."""

import os
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy.engine import make_url

from forget_lah.db import make_engine, session_factory
from services.mock_clinic.store import seed


def migrate(engine):
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def main():
    mock_url = os.environ.get("MOCK_DATABASE_URL")
    if not mock_url:
        return
    owner = make_url(os.environ["DATABASE_URL"])
    source = make_url(mock_url)
    if source.database != "forget_lah_mock" or source.username != "forget_lah_mock":
        raise ValueError("Unexpected simulator database or role")
    with psycopg.connect(
        host=owner.host,
        port=owner.port or 5432,
        dbname=owner.database,
        user=owner.username,
        password=owner.password,
        autocommit=True,
    ) as conn:
        conn.execute("SELECT pg_advisory_lock(76139001)")
        if not conn.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = %s", (source.username,)
        ).fetchone():
            conn.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(source.username), sql.Literal(source.password)
                )
            )
        if not conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (source.database,)
        ).fetchone():
            conn.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(source.database), sql.Identifier(source.username)
                )
            )
        conn.execute("REVOKE CONNECT ON DATABASE forget_lah_mock FROM PUBLIC")
        conn.execute("GRANT CONNECT ON DATABASE forget_lah_mock TO forget_lah_mock")
        engine = make_engine(mock_url)
        try:
            migrate(engine)
            seed(session_factory(engine))
        finally:
            engine.dispose()
        conn.execute("SELECT pg_advisory_unlock(76139001)")


if __name__ == "__main__":
    main()

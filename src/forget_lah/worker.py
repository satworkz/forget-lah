import logging
import signal
import threading
from datetime import timedelta

import httpx
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError

from forget_lah.db import AuditEvent, Job, make_engine, session_factory, uid, utcnow
from forget_lah.detector import detect
from forget_lah.settings import Settings
from forget_lah.source import DEMO_CLINIC_ID, read_candidates

log = logging.getLogger("forget_lah.worker")


def claim_job(factory) -> tuple[str, str] | None:
    now = utcnow()
    with factory.begin() as db:
        job = db.scalar(
            select(Job)
            .where(
                Job.available_at <= now,
                or_(Job.status == "queued", and_(Job.status == "running", Job.lease_until < now)),
            )
            .order_by(Job.available_at, Job.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not job:
            return None
        job.status, job.lease_token = "running", uid()
        job.lease_until, job.attempts = now + timedelta(seconds=30), job.attempts + 1
        return job.id, job.lease_token


def finish_job(factory, job_id: str, lease_token: str) -> bool:
    with factory.begin() as db:
        job = db.scalar(
            select(Job)
            .where(
                Job.id == job_id,
                Job.status == "running",
                Job.lease_token == lease_token,
                Job.lease_until > utcnow(),
            )
            .with_for_update()
        )
        if not job:
            return False
        # M1 proves durable job processing. It never pretends a model or provider was called.
        db.add(
            AuditEvent(
                clinic_id=job.clinic_id,
                case_id=job.case_id,
                event_type="FOUNDATION_CASE_READY",
                details={"note": "Ready for the agent runtime milestone; no outreach sent"},
            )
        )
        job.status, job.lease_until, job.lease_token = "done", None, None
        return True


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    settings = Settings()
    factory = session_factory(make_engine(settings.database_url.get_secret_value()))
    stopped = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stopped.set())
    while not stopped.is_set():
        try:
            created = detect(factory, DEMO_CLINIC_ID, read_candidates(settings.mock_clinic_url))
            if created:
                log.info("synthetic_cases_created=%s", created)
            for _ in range(50):
                claim = claim_job(factory)
                if not claim:
                    break
                finish_job(factory, *claim)
        except (httpx.HTTPError, SQLAlchemyError, ValueError) as exc:
            # No response bodies, credentials, names or connection strings in routine logs.
            log.warning(
                "worker_cycle_failed error_type=%s; retry_in_seconds=10", type(exc).__name__
            )
        stopped.wait(10)


if __name__ == "__main__":
    main()

import logging
import signal
import threading
import time
from datetime import timedelta

import httpx
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError

from forget_lah.channel import channel_tick
from forget_lah.db import AuditEvent, FollowupCase, Job, make_engine, session_factory, uid, utcnow
from forget_lah.detector import detect
from forget_lah.runtime.engine import claim_run, process_run
from forget_lah.runtime.startup import queue_case_review, queue_ready_reviews
from forget_lah.settings import Settings
from forget_lah.source import DEMO_CLINIC_ID, read_candidates
from forget_lah.translations import translate_one

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


def finish_job(factory, job_id: str, lease_token: str, *, settings=None) -> bool:
    settings = settings or Settings()
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
        case = db.scalar(
            select(FollowupCase)
            .where(FollowupCase.id == job.case_id, FollowupCase.clinic_id == job.clinic_id)
            .with_for_update()
        )
        db.add(
            AuditEvent(
                clinic_id=job.clinic_id,
                case_id=job.case_id,
                event_type="FOUNDATION_CASE_READY",
                details={
                    "note": "Foundation processing finished; automatic review may now be queued. No outreach sent."
                },
            )
        )
        job.status, job.lease_until, job.lease_token = "done", None, None
        queue_case_review(db, case, settings)
        return True


def run_lane(name, task, stopped, idle_seconds):
    """Network waits in one lane never hold up another; each task owns its sessions."""
    while not stopped.is_set():
        try:
            worked = task()
        except (httpx.HTTPError, SQLAlchemyError, ValueError) as exc:
            log.warning("worker_lane_failed lane=%s error_type=%s", name, type(exc).__name__)
            stopped.wait(1)
            continue
        if not worked:
            stopped.wait(idle_seconds)


def run_lanes(tasks, stopped, idle_seconds):
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

    with ThreadPoolExecutor(max_workers=len(tasks), thread_name_prefix="followup") as pool:
        futures = [pool.submit(run_lane, name, task, stopped, idle_seconds) for name, task in tasks]
        try:
            # A lane terminating unexpectedly must restart the supervised worker,
            # never silently leave a channel or case queue unattended.
            while not stopped.is_set():
                done, _ = wait(futures, timeout=0.5, return_when=FIRST_COMPLETED)
                if done:
                    for future in done:
                        future.result()
                    if not stopped.is_set():
                        raise RuntimeError("Worker lane stopped unexpectedly")
        finally:
            stopped.set()


def worker_tasks(factory, settings):
    next_detection = 0.0
    next_control = 0.0

    def control():
        nonlocal next_detection, next_control
        now = time.monotonic()
        if now < next_control:
            return False
        next_control = now + 1
        if now >= next_detection:
            next_detection = now + settings.source_poll_interval_seconds
            try:
                created = detect(factory, DEMO_CLINIC_ID, read_candidates(settings.mock_clinic_url))
                if created:
                    log.info("synthetic_cases_created=%s", created)
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("source_poll_failed error_type=%s", type(exc).__name__)
        for _ in range(50):
            claim = claim_job(factory)
            if not claim:
                break
            finish_job(factory, *claim, settings=settings)
        queue_ready_reviews(factory, settings)
        return False

    def agent():
        activation = claim_run(factory)
        if not activation:
            return False
        process_run(factory, settings, *activation)
        return True

    return [
        ("control", control),
        ("translation", lambda: translate_one(factory, settings)),
        ("whatsapp", lambda: channel_tick(factory, settings)),
        *[(f"agent-{i + 1}", agent) for i in range(settings.agent_parallelism)],
    ]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    settings = Settings()
    factory = session_factory(make_engine(settings.database_url.get_secret_value()))
    stopped = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stopped.set())
    log.info(
        "worker_started agent_parallelism=%s idle_seconds=%s",
        settings.agent_parallelism,
        settings.worker_idle_seconds,
    )
    run_lanes(worker_tasks(factory, settings), stopped, settings.worker_idle_seconds)


if __name__ == "__main__":
    main()

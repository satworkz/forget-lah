from datetime import UTC, timedelta

from sqlalchemy import select

from forget_lah.db import utcnow
from forget_lah.runtime.models import ModelBudget


def reserve_call(db, settings):
    """Caller must commit before HTTP. Return a denial code and optional retry delay."""
    # Preserve the historic singleton ID and usage when switching providers.
    budget = db.scalar(select(ModelBudget).where(ModelBudget.id == "organiser").with_for_update())
    if budget is None:
        return "MODEL_BUDGET_UNAVAILABLE", 0
    now = utcnow()
    if budget.day != now.date().isoformat():
        budget.day, budget.calls = now.date().isoformat(), 0
    if budget.calls >= settings.agent_daily_call_limit:
        return "DAILY_MODEL_BUDGET_EXHAUSTED", 0
    next_at = budget.next_allowed_at
    if next_at and next_at.tzinfo is None:
        next_at = next_at.replace(tzinfo=UTC)
    if next_at and next_at > now:
        return "MODEL_PACING", (next_at - now).total_seconds()
    budget.calls += 1
    budget.next_allowed_at = now + timedelta(seconds=settings.agent_min_interval_seconds)
    return None, 0

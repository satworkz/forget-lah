"""One explicit, synthetic, budgeted connection check; never executes a tool."""

import logging

from sqlalchemy.exc import SQLAlchemyError

from forget_lah.db import make_engine, session_factory, uid
from forget_lah.runtime.budget import reserve_call
from forget_lah.runtime.contracts import ToolDecision, parse_decision
from forget_lah.runtime.provider import ModelError, base_model_for
from forget_lah.settings import Settings


def check_model(settings, factory, model=None):
    if settings.agent_model_mode == "mock":
        return {"ok": False, "code": "SIMULATION_SELECTED"}
    if not settings.model_configured:
        return {"ok": False, "code": "MODEL_NOT_CONFIGURED"}
    with factory.begin() as db:
        error, delay = reserve_call(db, settings)
    if error:
        return {"ok": False, "code": error, "retry_after_seconds": round(delay + 0.5)}
    request_id = uid()
    observation = {
        "role": "coordinator",
        "request_id": request_id,
        "expected_case_version": 1,
        "goal": "Connection check only. Propose read_followup_context as your first step.",
        "latest_event": {"id": uid(), "kind": "started", "content": ""},
        "tools": [],
        "returned_specialists": [],
        "specialist_reports": [],
        "handoff": None,
    }
    try:
        reply = (model or base_model_for(settings, settings.agent_model_mode)).decide(observation)
        decision = parse_decision(reply.text, request_id, 1)
        if not isinstance(decision, ToolDecision) or decision.tool_name != "read_followup_context":
            return {"ok": False, "code": "MODEL_UNEXPECTED_DECISION"}
        return {
            "ok": True,
            "code": "MODEL_CONNECTION_VERIFIED",
            "provider": settings.agent_model_mode,
            "input_tokens": reply.input_tokens,
            "output_tokens": reply.output_tokens,
            "latency_ms": reply.latency_ms,
        }
    except ModelError as exc:
        return {"ok": False, "code": exc.code}
    except ValueError:
        return {"ok": False, "code": "MODEL_SCHEMA_INVALID"}


def main():
    # No request/response bodies, credentials, patient records or DB URL in output.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = Settings()
    engine = make_engine(settings.database_url.get_secret_value())
    try:
        try:
            result = check_model(settings, session_factory(engine))
        except SQLAlchemyError:
            result = {"ok": False, "code": "DATABASE_NOT_READY"}
        print(result)
        return 0 if result["ok"] else 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())

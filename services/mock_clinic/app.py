from datetime import UTC, datetime, timedelta

from fastapi import FastAPI

app = FastAPI(title="Synthetic clinic source", docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health/live")
def health():
    return {"status": "ok", "synthetic": True}


@app.get("/internal/candidates")
def candidates():
    # Stable episode IDs prevent duplicate cases across polls. Relative dates keep setup usable.
    now = datetime.now(UTC).replace(hour=2, minute=0, second=0, microsecond=0)
    return [
        {
            "patient_id": "20000000-0000-4000-8000-000000000001",
            "display_alias": "Mr Lim (demo)",
            "source_episode_ref": "DEMO-DENTAL-RECALL-01",
            "specialty": "dental",
            "record_type": "recall",
            "source_status": "due",
            "has_future_booking": False,
            "due_at": (now - timedelta(days=14)).isoformat(),
        },
        {
            "patient_id": "20000000-0000-4000-8000-000000000002",
            "display_alias": "Alex (demo)",
            "source_episode_ref": "DEMO-MYOPIA-VISIT-01",
            "specialty": "myopia",
            "record_type": "appointment",
            "source_status": "scheduled",
            "scheduled_at": (now + timedelta(days=3)).isoformat(),
        },
        {
            "patient_id": "20000000-0000-4000-8000-000000000003",
            "display_alias": "Priya (demo)",
            "source_episode_ref": "DEMO-ANTENATAL-VISIT-01",
            "specialty": "antenatal",
            "record_type": "appointment",
            "source_status": "no_show",
            "scheduled_at": (now - timedelta(days=1)).isoformat(),
        },
    ]

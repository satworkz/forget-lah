import secrets

from sqlalchemy import select

from forget_lah.auth import hasher
from forget_lah.db import Clinic, Membership, Principal, make_engine, session_factory
from forget_lah.service_identity import AUTOMATION_EMAIL, AUTOMATION_PRINCIPAL_ID
from forget_lah.settings import Settings
from forget_lah.source import DEMO_CLINIC_ID


def seed(factory, email: str, password: str) -> None:
    if len(password) < 16:
        raise ValueError("Generate a local demo password with at least 16 characters")
    with factory.begin() as db:
        if not db.get(Clinic, DEMO_CLINIC_ID):
            db.add(Clinic(id=DEMO_CLINIC_ID, name="forget-lah Demonstration Clinic"))
            db.flush()
        user = db.scalar(select(Principal).where(Principal.email == email.casefold()))
        if not user:
            user = Principal(email=email.casefold(), password_hash=hasher.hash(password))
            db.add(user)
            db.flush()
            db.add(Membership(principal_id=user.id, clinic_id=DEMO_CLINIC_ID))


def seed_automation(factory) -> None:
    """Provision once. Never re-enable a revoked identity or membership."""
    with factory.begin() as db:
        if not db.get(Principal, AUTOMATION_PRINCIPAL_ID):
            db.add(
                Principal(
                    id=AUTOMATION_PRINCIPAL_ID,
                    email=AUTOMATION_EMAIL,
                    password_hash=hasher.hash(secrets.token_urlsafe(48)),
                )
            )
            db.flush()
            db.add(Membership(principal_id=AUTOMATION_PRINCIPAL_ID, clinic_id=DEMO_CLINIC_ID))


def main() -> None:
    settings = Settings()
    if not settings.demo_staff_password:
        raise ValueError("DEMO_STAFF_PASSWORD is required for initial setup")
    engine = make_engine(settings.database_url.get_secret_value())
    try:
        seed(
            session_factory(engine),
            settings.demo_staff_email,
            settings.demo_staff_password.get_secret_value(),
        )
        seed_automation(session_factory(engine))
        print(
            "Synthetic clinic and staff account are ready. Existing credentials were not changed."
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()

"""Register distinct team test phones without replacing existing enrollment."""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = depends_on = None


def upgrade():
    # Migration 0008 uses model metadata, so fresh installs already have this constraint.
    constraints = sa.inspect(op.get_bind()).get_unique_constraints("channel_binding")
    if any(item["name"] == "uq_channel_phone" for item in constraints):
        return
    with op.batch_alter_table("channel_binding") as batch:
        batch.create_unique_constraint("uq_channel_phone", ["clinic_id", "recipient"])


def downgrade():
    raise RuntimeError("Forward-only: preserve team phone registrations")
